from fastapi import APIRouter
from src.api.schemas import HealthResponse
from src.db.database import get_pool
from src.cache.redis_client import get_redis
from src.app import trie

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Check all three services are reachable.
    Returns status of database, Redis, and Trie.
    Used by Docker healthcheck and monitoring tools.
    """
    # Check PostgreSQL
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        db_status = "healthy"
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"

    # Check Redis
    try:
        r = await get_redis()
        await r.ping()
        redis_status = "healthy"
    except Exception as e:
        redis_status = f"unhealthy: {str(e)}"

    return HealthResponse(
        status   = "ok",
        database = db_status,
        redis    = redis_status,
        trie     = {
            "words": trie.size(),
        }
    )