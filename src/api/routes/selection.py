"""
Records when a user selects a suggestion.
Only this route (and /search) use get_session — no other routes
are affected by cookie logic.
"""
from fastapi import APIRouter, Request, Response, Depends
from pydantic import BaseModel
from src.cache.redis_client import add_to_history
from src.cache.session import get_session
from src.app import trie

router = APIRouter()


class SelectionRequest(BaseModel):
    word: str


@router.post("/select")
async def record_selection(
    request   : Request,
    response  : Response,
    body      : SelectionRequest,
    session_id: str = Depends(get_session),   # ← only this route
):
    """
    Called when user clicks or presses Enter on a suggestion.

    Effects:
      1. Word added to this session's personal history in Redis
      2. Word's global frequency incremented in the Trie
         (clicking is a stronger signal than just typing)
    """
    word = body.word.lower().strip()

    # Only record complete words that actually exist in the Trie
    # Partial prefixes should never end up in personal history
    if not trie.search(word):
        return {
            "message": f"'{word}' is not a known word — not recorded",
            "session": session_id[:8]
        }

    await add_to_history(session_id, word)
    trie.increment_frequency(word)

    return {"message": f"Recorded: '{word}'", "session": session_id[:8]}

@router.post("/history/clear")
async def clear_personal_history(
    request   : Request,
    response  : Response,
    session_id: str = Depends(get_session),
):
    """Clear this session's personal history — useful for testing."""
    from src.cache.redis_client import clear_history
    await clear_history(session_id)
    return {"message": "History cleared", "session": session_id[:8]}