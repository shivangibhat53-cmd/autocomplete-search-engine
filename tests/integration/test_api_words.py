"""
Integration tests for word insert and delete endpoints.
"""
import pytest
from httpx import AsyncClient, ASGITransport
from src.api.main import app


@pytest.fixture(scope="module")
async def client(db_pool, redis_client):
    async with AsyncClient(
        transport = ASGITransport(app=app),
        base_url  = "http://test",
    ) as ac:
        yield ac


@pytest.mark.asyncio
async def test_insert_word(client):
    """Insert a word and verify it's searchable."""
    response = await client.post(
        "/words",
        json={"word": "streamlit", "frequency": 50}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["word"]      == "streamlit"
    assert data["frequency"] == 50


@pytest.mark.asyncio
async def test_insert_word_persisted_to_db(client, db_pool):
    """Inserted word must be in PostgreSQL."""
    await client.post(
        "/words",
        json={"word": "fastapi", "frequency": 30}
    )
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT word, frequency FROM words WHERE word = $1",
            "fastapi"
        )
    assert row is not None
    assert row["word"]      == "fastapi"
    assert row["frequency"] >= 30


@pytest.mark.asyncio
async def test_insert_duplicate_updates_frequency(client):
    """Inserting same word twice sums the frequency."""
    await client.post("/words",
                      json={"word": "python", "frequency": 10})
    r2 = await client.post("/words",
                           json={"word": "python", "frequency": 5})
    assert r2.json()["frequency"] == 15


@pytest.mark.asyncio
async def test_delete_word(client):
    """Delete a word and verify it's no longer searchable."""
    await client.post("/words",
                      json={"word": "pytorch", "frequency": 10})

    # Confirm it exists
    search = await client.get("/search?q=py")
    words  = [r["word"] for r in search.json()["results"]]
    assert "pytorch" in words

    # Delete it
    delete = await client.delete("/words/pytorch")
    assert delete.status_code == 200

    # Confirm it's gone
    search2 = await client.get("/search?q=py")
    words2  = [r["word"] for r in search2.json()["results"]]
    assert "pytorch" not in words2


@pytest.mark.asyncio
async def test_delete_nonexistent_word(client):
    """Deleting a word that doesn't exist returns 404."""
    response = await client.delete("/words/doesnotexist999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_insert_empty_word_rejected(client):
    """Empty word should be rejected with 422."""
    response = await client.post(
        "/words", json={"word": "", "frequency": 1}
    )
    assert response.status_code == 422