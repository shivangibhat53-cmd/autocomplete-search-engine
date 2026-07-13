"""
All database queries live here.
Routes never write raw SQL — they call these functions.
This keeps SQL in one place and makes testing easier.
"""
import asyncpg
from src.db.database import get_pool


async def get_all_words() -> list[dict]:
    """
    Fetch all words and frequencies from the database.
    Called at startup to populate the Trie from persisted data.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT word, frequency
            FROM words
            ORDER BY frequency DESC
        """)
    return [dict(row) for row in rows]


async def upsert_word(word: str, frequency: int = 1) -> dict:
    """
    Insert a word or update its frequency if it already exists.

    ON CONFLICT DO UPDATE means:
      - if word doesn't exist → insert it
      - if word exists → add frequency to existing count

    This is called every time a user adds a word or the search
    frequency is incremented.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO words (word, frequency)
            VALUES ($1, $2)
            ON CONFLICT (word)
            DO UPDATE SET
                frequency  = words.frequency + EXCLUDED.frequency,
                updated_at = NOW()
            RETURNING word, frequency
        """, word.lower().strip(), frequency)
    return dict(row)


async def delete_word(word: str) -> bool:
    """
    Delete a word from the database.
    Returns True if a row was deleted, False if word didn't exist.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("""
            DELETE FROM words WHERE word = $1
        """, word.lower().strip())

    # result is a string like "DELETE 1" or "DELETE 0"
    return result == "DELETE 1"


async def get_word(word: str) -> dict | None:
    """Fetch a single word's data. Returns None if not found."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT word, frequency, created_at, updated_at
            FROM words
            WHERE word = $1
        """, word.lower().strip())
    return dict(row) if row else None


async def get_top_words(limit: int = 20) -> list[dict]:
    """Fetch the most frequently searched words."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT word, frequency
            FROM words
            ORDER BY frequency DESC
            LIMIT $1
        """, limit)
    return [dict(row) for row in rows]