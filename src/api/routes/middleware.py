"""
Middleware:
  - LoggingMiddleware: logs every request with timing and session ID
    Session ID is optional in the log — routes that don't use
    get_session won't have request.state.session_id set.
"""
import time
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logging.basicConfig(
    level  = logging.INFO,
    format = "%(asctime)s │ %(levelname)s │ %(message)s",
    datefmt= "%H:%M:%S",
)
logger = logging.getLogger(__name__)


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Logs every request. Session ID is included only when
    the route used get_session (i.e. request.state.session_id exists).
    Health, docs, stats — no session ID in the log, which is correct.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        start    = time.perf_counter()
        response = await call_next(request)
        duration = (time.perf_counter() - start) * 1000

        # session_id is only present if the route used get_session
        session_part = ""
        if hasattr(request.state, "session_id"):
            session_part = f" [session={request.state.session_id[:8]}...]"

        logger.info(
            f"{request.method} {request.url.path} "
            f"→ {response.status_code} "
            f"({duration:.1f}ms)"
            f"{session_part}"
        )

        return response