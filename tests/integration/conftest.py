"""
Integration test configuration.
Sets up database and Redis connections for tests.
Requires Docker containers to be running:
  docker compose -f docker-compose.dev.yml up -d postgres redis
"""
import pytest
import asyncio
import os

# Point to test database
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://postgres:password@localhost:5432/autocomplete_test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")


@pytest.fixture(scope="session")
def event_loop():
    """Single event loop for all integration tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def db_pool():
    """Create database pool and schema for tests."""
    from src.db.database import init_db, close_db, get_pool
    await init_db()
    pool = await get_pool()

    # Create test table
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS words (
                id         SERIAL PRIMARY KEY,
                word       TEXT UNIQUE NOT NULL,
                frequency  INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_words_word
                ON words(word);
        """)

    yield pool

    # Clean up after all tests
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM words")

    await close_db()


@pytest.fixture(scope="session")
async def redis_client():
    """Redis connection for tests."""
    from src.cache.redis_client import init_redis, close_redis, get_redis
    await init_redis()
    r = await get_redis()
    yield r

    # Clean up test keys
    await r.flushdb()
    await close_redis()


@pytest.fixture(autouse=True)
async def clean_between_tests(db_pool, redis_client):
    """
    Clean database and Redis between each test.
    Ensures tests don't interfere with each other.
    """
    yield

    # Clean after each test
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM words")
    await redis_client.flushdb()