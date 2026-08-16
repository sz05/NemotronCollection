"""Checkpoint 2: end-to-end chat round trip through the real FastAPI app,
DB, and repository layer. The Nemotron network call itself is mocked (no
real API key is available in this environment) but everything else --
auth cookie, session creation, header handling, persistence -- is
exercised for real.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.models import ChatSession, FeedbackEntry
from app.state import feedback_question_store
from main import app


@pytest.fixture
async def client():
    """Unauthenticated client (for testing the auth gate itself)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_chat_round_trip_persists_and_never_leaks_key(auth_client, db_session):
    session_resp = await auth_client.post("/session")
    assert session_resp.status_code == 200
    session_id = session_resp.json()["id"]

    with patch(
        "app.routers.chat.send_chat_message", new=AsyncMock(return_value="Hi! How can I help?")
    ) as mocked:
        chat_resp = await auth_client.post(
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
    # First user message became the sidebar title.
    assert stored.title == "hello"

    # The key must never have been persisted alongside the session either.
    assert "nvapi-test-secret-should-not-leak" not in str(stored.messages)

    # cleanup
    await db_session.execute(delete(FeedbackEntry).where(FeedbackEntry.session_id == session_id))
    await db_session.execute(delete(ChatSession).where(ChatSession.id == session_id))
    await db_session.commit()


async def test_chat_requires_login(client):
    resp = await client.post(
        "/chat",
        json={"session_id": str(uuid.uuid4()), "message": "hi"},
        headers={"X-Nemotron-Key": "nvapi-test"},
    )
    assert resp.status_code == 401


async def test_chat_without_key_or_stored_key_is_rejected(auth_client, db_session):
    session_resp = await auth_client.post("/session")
    session_id = session_resp.json()["id"]

    # No header and the test user has no stored key -> 401 asking for one.
    resp = await auth_client.post("/chat", json={"session_id": session_id, "message": "hi"})
    assert resp.status_code == 401
    assert "API key" in resp.json()["detail"]

    await db_session.execute(delete(ChatSession).where(ChatSession.id == session_id))
    await db_session.commit()


async def test_chat_uses_stored_key_when_no_header(auth_client, db_session):
    from app.services.auth import encrypt_api_key

    key_resp = await auth_client.put("/auth/nemotron-key", json={"api_key": "nvapi-stored"})
    assert key_resp.status_code == 200
    assert key_resp.json()["has_nemotron_key"] is True

    session_id = (await auth_client.post("/session")).json()["id"]
    try:
        with patch(
            "app.routers.chat.send_chat_message", new=AsyncMock(return_value="ok")
        ) as mocked:
            resp = await auth_client.post(
                "/chat", json={"session_id": session_id, "message": "hi"}
            )
        assert resp.status_code == 200
        # The decrypted stored key reached the Nemotron client.
        assert mocked.await_args.args[0] == "nvapi-stored"
        # Sanity: what's in the DB is not the plaintext key.
        assert encrypt_api_key("nvapi-stored") != "nvapi-stored"
    finally:
        await auth_client.delete("/auth/nemotron-key")
        await db_session.execute(
            delete(FeedbackEntry).where(FeedbackEntry.session_id == session_id)
        )
        await db_session.execute(delete(ChatSession).where(ChatSession.id == session_id))
        await db_session.commit()


async def test_chat_blocked_while_feedback_question_pending(auth_client, db_session):
    """A pending feedback question must be answered before the next turn."""
    session_resp = await auth_client.post("/session")
    session_id = session_resp.json()["id"]

    await feedback_question_store.set(uuid.UUID(session_id), "How was the last answer?")
    try:
        resp = await auth_client.post(
            "/chat",
            json={"session_id": session_id, "message": "next prompt"},
            headers={"X-Nemotron-Key": "nvapi-test"},
        )
        assert resp.status_code == 409
        assert "feedback question" in resp.json()["detail"]

        # Answering the question clears the block.
        answer_resp = await auth_client.post(
            "/feedback",
            json={
                "session_id": session_id,
                "question": "How was the last answer?",
                "answer": "Pretty good",
            },
        )
        assert answer_resp.status_code == 200

        with patch(
            "app.routers.chat.send_chat_message", new=AsyncMock(return_value="Sure!")
        ):
            resp = await auth_client.post(
                "/chat",
                json={"session_id": session_id, "message": "next prompt"},
                headers={"X-Nemotron-Key": "nvapi-test"},
            )
        assert resp.status_code == 200
    finally:
        await feedback_question_store.clear(uuid.UUID(session_id))
        await db_session.execute(
            delete(FeedbackEntry).where(FeedbackEntry.session_id == session_id)
        )
        await db_session.execute(delete(ChatSession).where(ChatSession.id == session_id))
        await db_session.commit()


async def test_chat_rejects_unknown_session(auth_client):
    resp = await auth_client.post(
        "/chat",
        json={"session_id": "00000000-0000-0000-0000-000000000000", "message": "hi"},
        headers={"X-Nemotron-Key": "nvapi-test"},
    )
    assert resp.status_code == 404


async def test_sessions_are_listed_per_user(auth_client, db_session):
    first = (await auth_client.post("/session")).json()["id"]
    second = (await auth_client.post("/session")).json()["id"]
    try:
        listed = (await auth_client.get("/sessions")).json()
        listed_ids = [s["id"] for s in listed]
        assert first in listed_ids and second in listed_ids

        detail = (await auth_client.get(f"/sessions/{first}")).json()
        assert detail["id"] == first
        assert detail["messages"] == []
    finally:
        for sid in (first, second):
            await db_session.execute(delete(ChatSession).where(ChatSession.id == sid))
        await db_session.commit()
