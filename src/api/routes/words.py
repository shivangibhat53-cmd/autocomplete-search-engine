from fastapi import APIRouter, HTTPException,Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from src.api.schemas import WordInsertRequest, WordInsertResponse, WordDeleteResponse
from src.cache.redis_client import invalidate_prefix
from src.db.models import upsert_word, delete_word
from src.app import trie, bk_tree 

limiter = Limiter(key_func=get_remote_address)
router  = APIRouter()


@router.post("/words", response_model=WordInsertResponse)
@limiter.limit("30/minute")
@router.post("/words")
async def insert_word(
    request: Request,
    body   : WordInsertRequest,
):
    router_state = request.app.state
    word         = body.word.lower().strip()

    if not word:
        raise HTTPException(400, "Word cannot be empty")

    # Write to Postgres — source of truth
    db_result = await upsert_word(word, body.frequency)

    # Notify BK-Tree service to stay in sync
    try:
        await router_state.bk_client.insert_word(
            word, body.frequency
        )
    except Exception as e:
        # Non-fatal — word is in DB, BK-Tree picks it up on restart
        print(f"BK-Tree sync failed for '{word}': {e}")

    # Notify all shards to insert into their Trie
    # Only the shard that owns this word's prefix will actually
    # store it — others ignore it based on their hash range
    shard_name = router_state.ring.get_shard_for_prefix(word)
    breaker    = router_state.breakers.get(shard_name)

    if breaker.is_available():
        client = router_state.clients.get(shard_name)
        try:
            await client.insert_word(word, body.frequency)
        except Exception as e:
            print(f"Shard {shard_name} insert failed: {e}")

    # Invalidate cache for all prefixes of this word
    for i in range(1, len(word) + 1):
        await invalidate_prefix(word[:i])

    return {
        "word"     : db_result["word"],
        "frequency": db_result["frequency"],
        "message"  : f"'{word}' added successfully",
    }

@router.delete("/words/{word}", response_model=WordDeleteResponse)
@limiter.limit("30/minute")
async def remove_word(request:Request, word: str):
    """
    Delete a word from both the Trie and PostgreSQL.
    Invalidates cache for all prefixes of this word.
    """
    word    = word.lower().strip()
    in_trie = trie.delete(word)
    in_db   = await delete_word(word)
    # Note: BK-Tree doesn't support deletion (common in practice)
    # The word will still appear in fuzzy results but with
    # reduced impact since frequency drops to 0 in the Trie.
    # A full BK-Tree rebuild happens on API restart.
    # This is an accepted trade-off — documented in production notes.

    if not in_trie and not in_db:
        raise HTTPException(
            status_code=404,
            detail=f"'{word}' not found"
        )
    

    # Invalidate cache
    for i in range(1, len(word) + 1):
        await invalidate_prefix(word[:i])

    return WordDeleteResponse(
        word    = word,
        deleted = True,
        message = f"'{word}' deleted successfully",
    )