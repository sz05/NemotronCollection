"""Checkpoint 2: end-to-end chat round trip through the real FastAPI app,
DB, and repository layer. The Nemotron network call itself is mocked (no
real API key is available in this environment) but everything else --
session creation, header handling, persistence -- is exercised for real.
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.models import ChatSession, FeedbackEntry
from main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_chat_round_trip_persists_and_never_leaks_key(client, db_session):
    session_resp = await client.post("/session")
    assert session_resp.status_code == 200
    session_id = session_resp.json()["id"]

    with patch(
        "app.routers.chat.send_chat_message", new=AsyncMock(return_value="Hi! How can I help?")
    ) as mocked:
        chat_resp = await client.post(
            "/chat",
            json={"session_id": session_id, "message": "hello"},
            headers={"X-Nemotron-Key": "nvapi-test-secret-should-not-leak"},
        )

    assert chat_resp.status_code == 200
    body = chat_resp.json()
    assert body["reply"] == "Hi! How can I help?"

    # The key was forwarded to the Nemotron client call...
    mocked.assert_awaited_once()
    assert mocked.await_args.args[0] == "nvapi-test-secret-should-not-leak"

    # ...but never appears anywhere in the HTTP response.
    assert "nvapi-test-secret-should-not-leak" not in chat_resp.text

    stored = await db_session.get(ChatSession, session_id)
    assert stored.messages == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "Hi! How can I help?"},
    ]

    # The key must never have been persisted alongside the session either.
    assert "nvapi-test-secret-should-not-leak" not in str(stored.messages)

    # cleanup
    await db_session.execute(delete(FeedbackEntry).where(FeedbackEntry.session_id == session_id))
    await db_session.execute(delete(ChatSession).where(ChatSession.id == session_id))
    await db_session.commit()


async def test_chat_requires_key_header(client, db_session):
    session_resp = await client.post("/session")
    session_id = session_resp.json()["id"]

    resp = await client.post("/chat", json={"session_id": session_id, "message": "hi"})
    assert resp.status_code == 422  # FastAPI rejects the missing required header

    await db_session.execute(delete(ChatSession).where(ChatSession.id == session_id))
    await db_session.commit()


async def test_chat_rejects_unknown_session(client):
    resp = await client.post(
        "/chat",
        json={"session_id": "00000000-0000-0000-0000-000000000000", "message": "hi"},
        headers={"X-Nemotron-Key": "nvapi-test"},
    )
    assert resp.status_code == 404
