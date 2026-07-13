"""
PostgreSQL connection pool using asyncpg.

asyncpg is a pure-Python async PostgreSQL driver — much faster than
psycopg2 because it never blocks the event loop. FastAPI runs on an
async event loop (asyncio), so blocking calls would freeze all requests.

Connection pool: instead of opening a new DB connection for every request
(expensive — ~50ms), we keep a pool of open connections and reuse them.
Pool size of 5-20 is typical for a small API.
"""
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

# Module-level pool — created once at startup, shared across all requests
_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    """Return the connection pool, creating it if it doesn't exist."""
    global _pool
    if _pool is None:
        raise RuntimeError("Database pool not initialised. Call init_db() first.")
    return _pool


async def init_db() -> None:
    """
    Create the connection pool and set up the database schema.
    Called once at FastAPI startup via the lifespan function.
    """
    global _pool

    database_url = os.getenv("DATABASE_URL",
                             "postgresql://postgres:password@localhost:5432/autocomplete")

    _pool = await asyncpg.create_pool(
        dsn=database_url,
        min_size=2,     # keep at least 2 connections open
        max_size=10,    # never open more than 10 connections
    )

    # Create the words table if it doesn't exist
    async with _pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS words (
                id        SERIAL PRIMARY KEY,
                word      TEXT UNIQUE NOT NULL,
                frequency INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_words_word
                ON words(word);

            CREATE INDEX IF NOT EXISTS idx_words_frequency
                ON words(frequency DESC);
        """)

    print("Database initialised")


async def close_db() -> None:
    """
    Close the connection pool.
    Called once at FastAPI shutdown via the lifespan function.
    """
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
    print("Database pool closed")