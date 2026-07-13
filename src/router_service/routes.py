"""
Router service endpoints.

/search         → routes to correct shard via consistent hashing
/stats          → aggregates stats from all shards
/admin/shards   → manage shards at runtime (add, remove, list)
/admin/ring     → inspect the routing table
/health         → router's own health + all shard statuses
"""
from fastapi import APIRouter, Query, HTTPException, Request, Response, Depends
from src.router_service.circuit_breaker import CircuitBreakerRegistry
from src.cache.redis_client import (
    get_cached, set_cache,
    get_history_matching_prefix,
    add_to_history,
    invalidate_prefix,
    clear_history as redis_clear,
)

from src.cache.session import get_session
from src.merge import merge_personal_and_global
from pydantic import BaseModel
from src.db.models import upsert_word
from src.api.schemas import WordInsertRequest

from src.cache.redis_client import invalidate_prefix

from src.app import bk_tree
router = APIRouter()


# ── Search ────────────────────────────────────────────────────
@router.get("/search")
async def search(
    request   : Request,
    response  : Response,
    q         : str  = Query(..., min_length=1, max_length=100),
    limit     : int  = Query(default=10, ge=1, le=50),
    fuzzy     : bool = Query(default=False),
    session_id: str  = Depends(get_session),
):
    router_state = request.app.state
    q            = q.lower().strip()

    # Personal history
    personal = await get_history_matching_prefix(
        session_id, q, limit=5
    )

    # Check cache
    cached = await get_cached(q, limit)
    if cached:
        global_results = [(r["word"], r.get("score", 0))
                          for r in cached]
        merged = merge_personal_and_global(
            personal, global_results, limit=limit
        )
        return {
            "query"     : q,
            "results"   : merged,
            "total"     : len(merged),
            "from_cache": True,
            "shard"     : "cache",
        }

    if fuzzy:
        # ── Call dedicated BK-Tree microservice via gRPC ──────
        # No shard calls needed — BK-Tree service has all words
        # and is completely independent of shard health
         # Use smaller max_distance for short queries
        # "jav" with distance 2 would match "cat" (j→c, a→a, v→t = 2 edits)
        # Use distance 1 for queries under 4 chars, 2 for longer
        max_dist = 1 if len(q) <= 3 else 2
        try:
            bk_response    = await router_state.bk_client.fuzzy_search(
                q, max_distance=2, limit=limit
            )
            global_results = [
                (r["word"], float(r["frequency"]))
                for r in bk_response["results"]
                # Filter out results where distance equals word length
                # (means the match is essentially random)
                if r["distance"] < len(q)
            ]
            shard_used = "bk-tree-service"

        except Exception as e:
            # BK-Tree service is down — degrade gracefully to
            # prefix-only search rather than returning an error
            print(f"BK-Tree service unavailable: {e} "
                  f"— falling back to prefix search")
            global_results = []
            shard_used     = "fallback-prefix"

    else:
        # ── Consistent hash routing for prefix search ──────────
        shard_name = router_state.ring.get_shard_for_prefix(q)
        breaker    = router_state.breakers.get(shard_name)

        if not breaker.is_available():
            shard_name = _find_fallback_shard(
                router_state.ring,
                router_state.breakers,
                exclude=shard_name,
            )
            if not shard_name:
                raise HTTPException(
                    503, "No healthy shards available"
                )

        client = router_state.clients.get(shard_name)
        try:
            shard_response = await client.search(
                q, limit, fuzzy=False
            )
            breaker.record_success()
        except Exception as e:
            breaker.record_failure()
            raise HTTPException(503, detail=str(e))

        global_results = [
            (r["word"], r.get("score", 0))
            for r in shard_response.get("results", [])
        ]
        shard_used = shard_name

    # Cache and merge
    await set_cache(q, limit,
                    [{"word": w, "score": s}
                     for w, s in global_results])

    merged = merge_personal_and_global(
        personal, global_results, limit=limit
    )

    return {
        "query"     : q,
        "results"   : merged,
        "total"     : len(merged),
        "from_cache": False,
        "shard"     : shard_used,
    }

class SelectionRequest(BaseModel):
    word: str

@router.post("/select")
async def record_selection(
    request   : Request,
    response  : Response,
    body      : SelectionRequest,
    session_id: str = Depends(get_session),
):
    """
    Record a word selection for personalization.
    Adds to this session's personal history in Redis.
    Also increments global frequency via the correct shard.
    """
    word = body.word.lower().strip()

    if not word:
        raise HTTPException(400, "Word cannot be empty")

    # Add to personal history in Redis
    await add_to_history(session_id, word)
    
    # Invalidate cache for all prefixes of this word
    # so next search gets fresh personal results
    for i in range(1, len(word) + 1):
        await invalidate_prefix(word[:i])  

    # Increment frequency on the correct shard
    router_state = request.app.state
    shard_name   = router_state.ring.get_shard_for_prefix(word)
    breaker      = router_state.breakers.get(shard_name)

    if breaker.is_available():
        client = router_state.clients.get(shard_name)
        try:
            await client.insert_word(word, 1)
        except Exception as e:
            print(f"Shard frequency update failed: {e}")

    return {
        "message"   : f"Recorded: '{word}'",
        "session"   : session_id[:8],
    }

@router.post("/history/clear")
async def clear_history(
    request   : Request,
    response  : Response,
    session_id: str = Depends(get_session),
):
    """Clear this session's personal search history."""
    from src.cache.redis_client import clear_history as redis_clear
    await redis_clear(session_id)
    return {"message": "History cleared", "session": session_id[:8]}


@router.post("/words")
async def insert_word(
    request: Request,
    body   : WordInsertRequest,
):
    """
    Insert a word via the router.
    Writes to Postgres, notifies BK-Tree service and correct shard.
    """
    router_state = request.app.state
    word         = body.word.lower().strip()

    if not word:
        raise HTTPException(400, "Word cannot be empty")

    # Write to Postgres
    db_result = await upsert_word(word, body.frequency)

    # Notify BK-Tree service
    try:
        await router_state.bk_client.insert_word(
            word, body.frequency
        )
    except Exception as e:
        print(f"BK-Tree sync failed for '{word}': {e}")

    # Notify correct shard
    shard_name = router_state.ring.get_shard_for_prefix(word)
    breaker    = router_state.breakers.get(shard_name)

    if breaker.is_available():
        client = router_state.clients.get(shard_name)
        try:
            await client.insert_word(word, body.frequency)
        except Exception as e:
            print(f"Shard {shard_name} insert failed: {e}")

    # Invalidate Redis cache
    for i in range(1, len(word) + 1):
        await invalidate_prefix(word[:i])

    return {
        "word"     : db_result["word"],
        "frequency": db_result["frequency"],
        "message"  : f"'{word}' added successfully",
    }
# ── Admin — shard management ──────────────────────────────────

class ShardRegistration(BaseModel):
    name   : str
    address: str   # "hostname:port"


@router.get("/admin/shards")
async def list_shards(request: Request):
    router_state    = request.app.state
    shards_in_ring  = set(router_state.ring.get_all_shards())
    shards          = []

    for name, client in router_state.clients.items():
        breaker = router_state.breakers.get(name)
        shards.append({
            "name"   : name,
            "address": client.address,
            "status" : breaker.status,
            "in_ring": name in shards_in_ring,   # ← use the set
        })

    return {"shards": shards, "total": len(shards)}


@router.post("/admin/shards")
async def add_shard(request: Request, body: ShardRegistration):
    """
    Register a new shard at runtime.
    Adds it to the hash ring — ~1/n of keys will start routing here.
    The new shard loads its words from Postgres on its own startup.
    """
    from src.router_service.grpc_client import ShardGRPCClient

    router_state = request.app.state
    name         = body.name
    address      = body.address

    if name in router_state.clients:
        raise HTTPException(400, f"Shard '{name}' already registered")

    # Create gRPC client for the new shard
    client = ShardGRPCClient(name, address)
    router_state.clients[name] = client

    # Add to ring
    router_state.ring.add_shard(name)

    # Add to health monitor
    router_state.monitor.clients[name] = client

    print(f"Added shard '{name}' at {address}")
    return {
        "message": f"Shard '{name}' added",
        "address": address,
        "note"   : "~1/n of keys now route to this shard"
    }


@router.delete("/admin/shards/{shard_name}")
async def remove_shard(request: Request, shard_name: str):
    """
    Remove a shard gracefully.
    Its keys are reassigned to the next clockwise shard.
    """
    router_state = request.app.state

    if shard_name not in router_state.clients:
        raise HTTPException(404, f"Shard '{shard_name}' not found")

    # Remove from ring
    router_state.ring.remove_shard(shard_name)

    # Close gRPC connection
    client = router_state.clients.pop(shard_name)
    await client.close()

    # Remove from health monitor
    router_state.monitor.clients.pop(shard_name, None)

    print(f"Removed shard '{shard_name}'")
    return {
        "message": f"Shard '{shard_name}' removed",
        "note"   : "Its keys reassigned to next clockwise shard"
    }


@router.get("/admin/ring")
async def routing_table(request: Request):
    """
    Show which shard handles which 2-char prefixes.
    Useful for debugging and understanding data distribution.
    """
    router_state = request.app.state
    table        = router_state.ring.routing_table()
    return {
        "routing_table": table,
        "shard_count"  : len(router_state.ring.get_all_shards()),
    }

@router.get("/admin/debug")
async def debug_ring(request: Request):
    """Temporary debug endpoint."""
    router_state = request.app.state
    ring         = router_state.ring
    return {
        "ring_size"      : len(ring.ring),
        "sorted_keys_len": len(ring.sorted_keys),
        "unique_shards"  : ring.get_all_shards(),
        "virtual_nodes"  : ring.virtual_nodes,
        "expected_total" : len(ring.get_all_shards()) * ring.virtual_nodes,
    }




# ── Health ────────────────────────────────────────────────────
@router.get("/health")
async def health(request: Request):
    """Router health + all shard statuses."""
    router_state   = request.app.state
    shard_statuses = router_state.breakers.all_statuses()

    healthy = sum(1 for s in shard_statuses.values()
                  if s == "closed")
    total   = len(shard_statuses)

    return {
        "status"       : "ok" if healthy > 0 else "degraded",
        "healthy_shards": healthy,
        "total_shards" : total,
        "shards"       : shard_statuses,
    }


@router.get("/stats")
async def stats(request: Request):
    """Aggregate stats from all healthy shards."""
    router_state = request.app.state
    all_stats    = []

    for name, client in router_state.clients.items():
        breaker = router_state.breakers.get(name)
        if not breaker.is_available():
            continue
        try:
            shard_stats = await client.get_stats()
            all_stats.append(shard_stats)
        except Exception:
            continue

    total_words = sum(s.get("word_count", 0) for s in all_stats)
    return {
        "total_words": total_words,
        "shards"     : all_stats,
    }


# ── Helper ────────────────────────────────────────────────────
def _find_fallback_shard(ring, breakers, exclude: str) -> str | None:
    """
    Find the next healthy shard when the primary is down.
    Tries all shards in the ring except the excluded one.
    """
    for shard in ring.get_all_shards():
        if shard != exclude and breakers.get(shard).is_available():
            return shard
    return None