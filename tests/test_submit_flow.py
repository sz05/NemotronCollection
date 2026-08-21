"""Submit-to-score flow: unlock gating (random 5-8 gap, deterministic per
session), Gemini scoring -> points = score% of the bucket ceiling, keep-highest
per chat, free-chat scoring on its own ceiling, and admin/CSRF gating. Real app
+ DB; auth is dev-login and Gemini is mocked.
"""

import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

import app.routers.proof as proof_router
from app.config import settings
from main import app

ADMIN_EMAIL = "submit_admin@example.com"
PARTICIPANT_EMAIL = "submit_participant@example.com"


@pytest_asyncio.fixture
async def admin_env():
    orig_dev, orig_admins = settings.dev_auth, settings.admin_emails
    settings.dev_auth = True
    settings.admin_emails = ADMIN_EMAIL
    try:
        yield
    finally:
        settings.dev_auth = orig_dev
        settings.admin_emails = orig_admins


async def _client_for(email: str) -> AsyncClient:
    c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    resp = await c.post("/auth/dev-login", json={"email": email})
    assert resp.status_code == 200, resp.text
    c.headers["X-CSRF-Token"] = resp.json()["csrf_token"]
    return c


@pytest_asyncio.fixture
async def admin_client(admin_env):
    c = await _client_for(ADMIN_EMAIL)
    try:
        yield c
    finally:
        await c.aclose()


@pytest_asyncio.fixture
async def participant_client(admin_env):
    c = await _client_for(PARTICIPANT_EMAIL)
    try:
        yield c
    finally:
        await c.aclose()


async def _make_task(admin_client, *, base_points=100) -> str:
    resp = await admin_client.post(
        "/tasks",
        json={
            "title": "Submit-flow task",
            "description": "desc",
            "difficulty": "medium",
            "base_points": base_points,
            "proof_types": [],
            "instructions": "",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _seed_user_messages(db_session, sid: str, n: int):
    """Put exactly n user messages on the session (bypasses Nemotron)."""
    from app.models import ChatSession

    session = await db_session.get(ChatSession, uuid.UUID(sid))
    session.messages = [{"role": "user", "content": f"m{i}"} for i in range(n)]
    db_session.add(session)
    await db_session.commit()


async def _cleanup_session(db_session, sid: str, task_id: str | None = None):
    from app.models import ChatSession, ChatSubmission, Task

    suid = uuid.UUID(sid)
    await db_session.execute(delete(ChatSubmission).where(ChatSubmission.session_id == suid))
    await db_session.execute(delete(ChatSession).where(ChatSession.id == suid))
    if task_id is not None:
        await db_session.execute(delete(Task).where(Task.id == uuid.UUID(task_id)))
    await db_session.commit()


async def test_submit_gate_score_and_keep_highest(
    admin_client, participant_client, db_session, monkeypatch
):
    task_id = await _make_task(admin_client, base_points=100)
    sid = (await participant_client.post("/session", json={"task_id": task_id})).json()["id"]
    suid = uuid.UUID(sid)
    try:
        # Below the first threshold -> locked (status + 409 on submit).
        t1 = proof_router._next_threshold(suid, 0)
        await _seed_user_messages(db_session, sid, t1 - 1)
        assert (await participant_client.get(f"/sessions/{sid}/submit-status")).json()["can_submit"] is False
        assert (await participant_client.post(f"/sessions/{sid}/submit")).status_code == 409

        before = (await participant_client.get("/score/total")).json()["total_score"]

        # Reach the threshold; Gemini scores 60 -> points = round(100 * 0.60) = 60.
        await _seed_user_messages(db_session, sid, t1)

        async def score_60(theme, msgs, **kw):
            assert theme == "desc"  # themed chat passes the task description
            return 60

        monkeypatch.setattr(proof_router, "score_submission", score_60)
        assert (await participant_client.get(f"/sessions/{sid}/submit-status")).json()["can_submit"] is True
        r = await participant_client.post(f"/sessions/{sid}/submit")
        assert r.status_code == 200, r.text
        assert r.json()["score"] == 60 and r.json()["points"] == 60
        assert r.json()["total_score"] == before + 60

        # Resubmit lower after reaching the next threshold -> keep-highest: the
        # user is shown the new (lower) score, but the total does not drop.
        t2 = proof_router._next_threshold(suid, 1)
        assert t2 > t1  # each submit pushes the bar 5-8 messages further
        await _seed_user_messages(db_session, sid, t2)

        async def score_20(theme, msgs, **kw):
            return 20

        monkeypatch.setattr(proof_router, "score_submission", score_20)
        r2 = await participant_client.post(f"/sessions/{sid}/submit")
        assert r2.status_code == 200, r2.text
        assert r2.json()["score"] == 20
        assert r2.json()["total_score"] == before + 60  # unchanged
        assert (await participant_client.get(f"/sessions/{sid}/submit-status")).json()["best_score"] == 60
    finally:
        await _cleanup_session(db_session, sid, task_id)


async def test_free_chat_uses_free_ceiling(participant_client, db_session, monkeypatch):
    # No task_id -> free chat, scored on sensible engagement, ceiling = free_chat_max_points.
    sid = (await participant_client.post("/session", json={})).json()["id"]
    suid = uuid.UUID(sid)
    try:
        t1 = proof_router._next_threshold(suid, 0)
        await _seed_user_messages(db_session, sid, t1)
        before = (await participant_client.get("/score/total")).json()["total_score"]

        async def score_80(theme, msgs, **kw):
            assert theme is None  # free chat -> no theme
            return 80

        monkeypatch.setattr(proof_router, "score_submission", score_80)
        r = await participant_client.post(f"/sessions/{sid}/submit")
        assert r.status_code == 200, r.text
        expected = round(80 / 100 * settings.free_chat_max_points)
        assert r.json()["points"] == expected
        assert r.json()["total_score"] == before + expected
    finally:
        await _cleanup_session(db_session, sid)


async def test_write_without_csrf_header_is_forbidden(participant_client):
    participant_client.headers.pop("X-CSRF-Token", None)
    resp = await participant_client.post("/session", json={})
    assert resp.status_code == 403


async def test_non_admin_cannot_create_task(participant_client):
    resp = await participant_client.post("/tasks", json={"title": "x", "description": "d"})
    assert resp.status_code == 403
