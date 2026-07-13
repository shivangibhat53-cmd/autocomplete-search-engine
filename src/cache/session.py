"""
Anonymous session management using FastAPI dependency injection.

Using Depends() instead of middleware means session cookie logic
runs ONLY in routes that explicitly declare they need it.
Health checks, docs, and stats never touch cookie logic at all.
"""
import uuid
from typing import Optional
from fastapi import Request, Response, Cookie

COOKIE_NAME    = "session_id"
HEADER_NAME    = "X-Session-ID"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365


async def get_session(
    request : Request,
    response: Response,
) -> str:
    """
    Read session ID from X-Session-ID header first,
    then fall back to cookie.

    Using a custom header is more reliable than cookies
    for programmatic clients (like Streamlit's requests library)
    because cookie domain matching can be tricky with localhost.
    """
    # Try header first (used by Streamlit)
    session_id = request.headers.get(HEADER_NAME)

    if session_id:
        # Header found — use it, also set cookie for browser clients
        response.set_cookie(
            key      = COOKIE_NAME,
            value    = session_id,
            max_age  = COOKIE_MAX_AGE,
            httponly = True,
            samesite = "lax",
        )
        request.state.session_id = session_id
        return session_id

    # Fall back to cookie (used by browser)
    session_id = request.cookies.get(COOKIE_NAME)

    if session_id is None:
        # Neither header nor cookie — generate new session
        session_id = str(uuid.uuid4())
        response.set_cookie(
            key      = COOKIE_NAME,
            value    = session_id,
            max_age  = COOKIE_MAX_AGE,
            httponly = True,
            samesite = "lax",
        )

    request.state.session_id = session_id
    return session_id