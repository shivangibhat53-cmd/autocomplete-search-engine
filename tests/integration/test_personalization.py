"""
Integration tests for personalization (session history).
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
async def test_select_adds_to_personal_history(client, redis_client):
    """Selecting a word adds it to Redis history."""
    session_id = "test-session-integration-001"

    # Insert word first
    await client.post("/words",
                      json={"word": "pytorch", "frequency": 10})

    # Select it
    response = await client.post(
        "/select",
        json    = {"word": "pytorch"},
        headers = {"X-Session-ID": session_id},
    )
    assert response.status_code == 200

    # Check Redis directly
    history = await redis_client.lrange(
        f"history:{session_id}", 0, -1
    )
    assert "pytorch" in history


@pytest.mark.asyncio
async def test_personal_result_appears_first(client):
    """Selected word appears first in search with personal badge."""
    session_id = "test-session-integration-002"

    # Insert two words
    await client.post("/words",
                      json={"word": "python",  "frequency": 100})
    await client.post("/words",
                      json={"word": "pytorch", "frequency": 10})

    # Select pytorch (lower frequency)
    await client.post(
        "/select",
        json    = {"word": "pytorch"},
        headers = {"X-Session-ID": session_id},
    )

    # Search — pytorch should appear first despite lower frequency
    response = await client.get(
        "/search?q=py",
        headers = {"X-Session-ID": session_id},
    )
    assert response.status_code == 200
    results = response.json()["results"]
    assert results[0]["word"]   == "pytorch"
    assert results[0]["source"] == "personal"


@pytest.mark.asyncio
async def test_clear_history(client, redis_client):
    """Clearing history removes personal results."""
    session_id = "test-session-integration-003"

    await client.post("/words",
                      json={"word": "python", "frequency": 10})
    await client.post(
        "/select",
        json    = {"word": "python"},
        headers = {"X-Session-ID": session_id},
    )

    # Clear history
    await client.post(
        "/history/clear",
        headers={"X-Session-ID": session_id}
    )

    # Personal history should be empty
    history = await redis_client.lrange(
        f"history:{session_id}", 0, -1
    )
    assert history == []