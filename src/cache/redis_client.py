"""
Redis cache for autocomplete results.

Why cache autocomplete?
  Every search request triggers a DFS traversal of the Trie.
  For popular prefixes like 'a' or 'the', thousands of users
  ask the same question every second. Caching means we compute
  the answer once and serve it instantly for 5 minutes.

Cache key format: "autocomplete:{prefix}:{limit}"
  e.g. "autocomplete:py:10"

TTL (Time To Live): 300 seconds (5 minutes)
  After 5 minutes Redis deletes the entry automatically.
  New words added during that window won't appear in cached
  results — acceptable trade-off for most use cases.
  We also manually invalidate on word insert/delete.
"""
import json
import redis.asyncio as aioredis
import os
from dotenv import load_dotenv
import asyncio

load_dotenv()
HISTORY_MAX_ITEMS = 50          # keep last 50 searches per session
HISTORY_TTL       = 60 * 60 * 24 * 30   # 30 days
TTL = 300   # cache entries expire after 5 minutes

_redis: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    """Return the Redis client, creating it if needed."""
    global _redis
    if _redis is None:
        raise RuntimeError("Redis not initialised. Call init_redis() first.")
    return _redis


async def init_redis() -> None:
    """
    Create Redis connection.
    Called once at FastAPI startup.
    """
    global _redis
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    for attempt in range(1, 6):
        try:
            _redis = aioredis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
            await _redis.ping()
            print(f"✅ Redis connected ({redis_url})")
            return
        except Exception as e:
            print(f"  Redis attempt {attempt}/5 failed: {e}")
            if attempt < 5:
                await asyncio.sleep(2)

    raise RuntimeError(f"Could not connect to Redis at {redis_url}")


async def close_redis() -> None:
    """Close Redis connection at shutdown."""
    global _redis
    if _redis:
        await _redis.close()
        _redis = None


async def get_cached(prefix: str, limit: int) -> list | None:
    """
    Try to get cached autocomplete results.
    Returns the list if found, None if cache miss.
    """
    r   = await get_redis()
    key = f"autocomplete:{prefix}:{limit}"
    val = await r.get(key)

    if val:
        return json.loads(val)   # deserialise JSON back to list
    return None                  # cache miss


async def set_cache(prefix: str, limit: int, results: list) -> None:
    """
    Store autocomplete results in Redis with TTL.
    Results are serialised to JSON string for storage.
    """
    r   = await get_redis()
    key = f"autocomplete:{prefix}:{limit}"
    await r.setex(key, TTL, json.dumps(results))


async def invalidate_prefix(prefix: str) -> None:
    """
    Delete all cached results that start with this prefix.
    Called when a new word is added or deleted — so stale
    results don't serve from cache.

    Uses Redis SCAN to find matching keys without blocking.
    (KEYS * blocks Redis — never use in production)
    """
    r       = await get_redis()
    pattern = f"autocomplete:{prefix}*"
    cursor  = 0

    while True:
        cursor, keys = await r.scan(cursor, match=pattern, count=100)
        if keys:
            await r.delete(*keys)
        if cursor == 0:
            break


async def flush_cache() -> int:
    """
    Clear all autocomplete cache entries.
    Returns number of keys deleted.
    Called from the admin endpoint.
    """
    r       = await get_redis()
    pattern = "autocomplete:*"
    count   = 0
    cursor  = 0

    while True:
        cursor, keys = await r.scan(cursor, match=pattern, count=100)
        if keys:
            await r.delete(*keys)
            count += len(keys)
        if cursor == 0:
            break

    return count

async def add_to_history(session_id: str, word: str) -> None:
    """
    Record a selected word into this session's personal history.

    Uses a Redis LIST:
      LPUSH adds to the front (most recent first)
      LTRIM keeps only the most recent HISTORY_MAX_ITEMS
      EXPIRE resets the TTL so active users never lose history,
      but abandoned sessions clean up automatically after 30 days

    We also remove any existing occurrence of this word first,
    so re-searching something moves it to the front instead of
    creating duplicate entries.
    """
    r   = await get_redis()
    key = f"history:{session_id}"

    # Remove existing occurrence (if any) so it moves to front, not duplicates
    await r.lrem(key, 0, word)

    await r.lpush(key, word)
    await r.ltrim(key, 0, HISTORY_MAX_ITEMS - 1)
    await r.expire(key, HISTORY_TTL)


async def get_history(session_id: str, limit: int = 50) -> list:
    """Return this session's search history, most recent first."""
    r   = await get_redis()
    key = f"history:{session_id}"
    return await r.lrange(key, 0, limit - 1)


async def get_history_matching_prefix(session_id: str, prefix: str,
                                      limit: int = 5) -> list:
    """
    Filter personal history to only words matching the current prefix.
    History is small (max 50 items) so a Python-side filter is fine —
    no need for a more complex Redis query.
    """
    history = await get_history(session_id, limit=HISTORY_MAX_ITEMS)
    prefix  = prefix.lower().strip()
    matches = [word for word in history if word.startswith(prefix)]
    return matches[:limit]


async def clear_history(session_id: str) -> None:
    """Delete a session's entire search history."""
    r   = await get_redis()
    key = f"history:{session_id}"
    await r.delete(key)