from fastapi import APIRouter, Query, Request, Response, Depends
from slowapi import Limiter
from slowapi.util import get_remote_address
from src.api.schemas import SearchResponse, SearchResult, TrieStatsResponse
from src.cache.redis_client import (
    get_cached, set_cache,
    get_history_matching_prefix,
)
from src.cache.session import get_session
from src.fuzzy import fuzzy_autocomplete
from src.merge import merge_personal_and_global
from src.app import trie,bk_tree
from src.db.models import get_top_words

limiter = Limiter(key_func=get_remote_address)
router  = APIRouter()


@router.get("/search", response_model=SearchResponse)
@limiter.limit("60/minute")
async def search(
    request   : Request,
    response  : Response,
    q         : str  = Query(..., min_length=1, max_length=100,
                             description="Search prefix"),
    limit     : int  = Query(default=10, ge=1, le=50),
    fuzzy     : bool = Query(default=False,
                             description="Enable fuzzy matching"),
    session_id: str  = Depends(get_session),   # ← only this route runs session logic
):
    """
    Personalized autocomplete.

    Flow:
      1. get_session dependency reads/creates cookie before this runs
      2. Fetch personal history matches for this prefix from Redis
      3. Fetch global suggestions from Trie cache (or Redis cache)
      4. Merge — personal first, global fills remaining slots
    """
    q = q.lower().strip()

    # Step 1 — personal history matches
    personal = await get_history_matching_prefix(
        session_id, q, limit=5
    )

    # Step 2 — global suggestions
    cached_global = await get_cached(q, limit)
    if cached_global:
        global_results = [(r["word"], r.get("score", 0))
                          for r in cached_global]
        from_cache = True
    else:
        if fuzzy:
            # ── BK-Tree fuzzy search (replaces brute force) ──
            raw = bk_tree.search(q, max_distance=2)
            """raw = fuzzy_autocomplete(trie, q,
                                     max_distance=2,
                                     limit=limit)"""
            global_results = [(word, freq)
                              for word, match_type, freq in raw]
        else:
            global_results = trie.autocomplete_with_scores(
                q, limit=limit
            )

        await set_cache(q, limit,
                        [{"word": w, "score": s}
                         for w, s in global_results])
        from_cache = False

    # Step 3 — merge personal + global, deduplicate
    merged  = merge_personal_and_global(personal, global_results,
                                        limit=limit)
    results = [SearchResult(**r) for r in merged]

    return SearchResponse(
        query      = q,
        results    = results,
        total      = len(results),
        from_cache = from_cache,
    )


@router.get("/stats", response_model=TrieStatsResponse)
async def stats():
    """
    Global Trie stats — no session needed.
    This route never touches cookie logic.
    """
    top_raw = await get_top_words(limit=20)
    bk_stats   = bk_tree.stats()
    top     = [
        SearchResult(word=r["word"], source="global",
                     score=float(r["frequency"]))
        for r in top_raw
    ]
    return TrieStatsResponse(
        total_words = trie.size(),
        top_words   = top,
        bk_tree_size  = bk_stats["size"],
        bk_tree_depth = bk_stats["depth"],
    )