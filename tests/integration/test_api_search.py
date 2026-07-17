"""
Integration tests for the search API.
Tests the full stack: FastAPI + PostgreSQL + Redis + Trie.
"""
import pytest
from httpx import AsyncClient, ASGITransport
from src.api.main import app


@pytest.fixture(scope="module")
async def client(db_pool, redis_client):
    """
    Test client that talks to the real FastAPI app
    with real database and Redis connections.
    """
    async with AsyncClient(
        transport = ASGITransport(app=app),
        base_url  = "http://test",
    ) as ac:
        yield ac


@pytest.mark.asyncio
async def test_health_check(client):
    """Health endpoint reports all services healthy."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"]   == "ok"
    assert data["database"] == "healthy"
    assert data["redis"]    == "healthy"


@pytest.mark.asyncio
async def test_search_empty_trie(client):
    """Search on empty Trie returns empty results."""
    response = await client.get("/search?q=py")
    assert response.status_code == 200
    data = response.json()
    assert data["total"]   == 0
    assert data["results"] == []


@pytest.mark.asyncio
async def test_search_after_insert(client):
    """Insert a word then search for it."""
    # Insert
    insert = await client.post(
        "/words",
        json={"word": "python", "frequency": 10}
    )
    assert insert.status_code == 200

    # Search
    response = await client.get("/search?q=py")
    assert response.status_code == 200
    data  = response.json()
    words = [r["word"] for r in data["results"]]
    assert "python" in words


@pytest.mark.asyncio
async def test_search_result_cached_on_second_call(client):
    """Second identical search should hit cache."""
    await client.post(
        "/words",
        json={"word": "python", "frequency": 10}
    )

    # First call — not cached
    r1 = await client.get("/search?q=py")
    assert r1.json()["from_cache"] is False

    # Second call — cached
    r2 = await client.get("/search?q=py")
    assert r2.json()["from_cache"] is True


@pytest.mark.asyncio
async def test_search_respects_limit(client):
    """Search results respect the limit parameter."""
    for word, freq in [
        ("python", 10), ("pytorch", 8),
        ("pycharm", 6), ("pandas",  4),
    ]:
        await client.post(
            "/words", json={"word": word, "frequency": freq}
        )

    response = await client.get("/search?q=py&limit=2")
    assert response.status_code == 200
    assert len(response.json()["results"]) <= 2


@pytest.mark.asyncio
async def test_search_invalid_query_too_short(client):
    """Query shorter than min_length returns 422."""
    response = await client.get("/search?q=")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_stats_endpoint(client):
    """Stats endpoint returns word count."""
    response = await client.get("/stats")
    assert response.status_code == 200
    data = response.json()
    assert "total_words" in data