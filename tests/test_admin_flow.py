"""Admin flow: allowlist gating, proof review + point awards via the
quality_factor (% of points), regrade-upsert raising points on a better PoC,
participant grade visibility, quality_factor clamp (C2), and the self-review
block (C1). Real app + DB; only auth is dev-login.
"""

import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.config import settings
from main import app

ADMIN_EMAIL = "admin_flow@example.com"
PARTICIPANT_EMAIL = "participant_flow@example.com"


@pytest_asyncio.fixture
async def admin_env():
    """Enable dev-login and put ADMIN_EMAIL on the admin allowlist."""
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


async def _make_task(admin_client, *, difficulty="medium", base_points=100) -> str:
    resp = await admin_client.post(
        "/tasks",
        json={
            "title": "Admin-flow task",
            "description": "desc",
            "difficulty": difficulty,
            "base_points": base_points,
            "proof_types": ["url"],
            "instructions": "",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _submit_url_proof(client, session_id: str, url: str):
    return await client.post(
        f"/sessions/{session_id}/proof",
        data={"proof_type": "url", "warning_ack": "true", "url": url},
    )


async def _cleanup_task(db_session, task_id: uuid.UUID):
    from app.models import ChatSession, PointAward, ProofSubmission, Task

    await db_session.execute(delete(PointAward).where(PointAward.task_id == task_id))
    await db_session.execute(delete(ProofSubmission).where(ProofSubmission.task_id == task_id))
    await db_session.execute(delete(ChatSession).where(ChatSession.task_id == task_id))
    await db_session.execute(delete(Task).where(Task.id == task_id))
    await db_session.commit()


async def test_review_awards_and_regrade_raises_points(
    admin_client, participant_client, db_session
):
    from app.models import PointAward

    task_id = await _make_task(admin_client)  # base 100; points = base * qf
    try:
        # Participant starts a task-scoped chat and submits a proof.
        sid = (
            await participant_client.post("/session", json={"task_id": task_id})
        ).json()["id"]
        assert (await _submit_url_proof(participant_client, sid, "https://e.com/poc1")).status_code == 200

        # A non-admin cannot see the admin queue.
        assert (await participant_client.get("/admin/proofs")).status_code == 403

        # Admin sees exactly this pending submission.
        queue = [p for p in (await admin_client.get("/admin/proofs")).json() if p["task_id"] == task_id]
        assert len(queue) == 1 and queue[0]["status"] == "pending"
        proof_id = queue[0]["id"]

        # Verify at 50% -> round(100 * 0.5) = 50 (% of the task's points).
        rev = await admin_client.post(
            f"/admin/proofs/{proof_id}/review",
            json={"decision": "verified", "quality_factor": 0.5},
        )
        assert rev.status_code == 200, rev.text
        assert rev.json()["percent"] == 50
        assert rev.json()["points"] == 50

        # Participant sees their grade on their own submission.
        status = (await participant_client.get(f"/sessions/{sid}/proof")).json()
        assert status[0]["percent"] == 50 and status[0]["points"] == 50

        # The award now counts toward the participant's total score.
        total = (await participant_client.get("/score/total")).json()["total_score"]
        assert total == 50  # no chat score yet, so total == the bonus

        # Resubmit a better PoC; admin re-grades higher -> award upserts upward.
        assert (await _submit_url_proof(participant_client, sid, "https://e.com/poc2")).status_code == 200
        queue2 = [p for p in (await admin_client.get("/admin/proofs")).json() if p["task_id"] == task_id]
        proof2 = next(p for p in queue2 if p["id"] != proof_id)
        rev2 = await admin_client.post(
            f"/admin/proofs/{proof2['id']}/review",
            json={"decision": "verified", "quality_factor": 0.9},
        )
        assert rev2.status_code == 200, rev2.text
        assert rev2.json()["points"] == 90  # round(100 * 0.9)

        # Exactly ONE award for (participant, task), updated to the higher grade.
        awards = (
            await db_session.execute(
                select(PointAward).where(PointAward.task_id == uuid.UUID(task_id))
            )
        ).scalars().all()
        assert len(awards) == 1 and awards[0].points == 90
    finally:
        await _cleanup_task(db_session, uuid.UUID(task_id))


async def test_pending_submission_blocks_resubmission(
    admin_client, participant_client, db_session
):
    task_id = await _make_task(admin_client)
    try:
        sid = (
            await participant_client.post("/session", json={"task_id": task_id})
        ).json()["id"]
        assert (await _submit_url_proof(participant_client, sid, "https://e.com/p1")).status_code == 200

        # A second submission while the first is still pending is refused.
        blocked = await _submit_url_proof(participant_client, sid, "https://e.com/p2")
        assert blocked.status_code == 409

        # Once the first is resolved (rejected here), resubmission is allowed.
        proof_id = [
            p for p in (await admin_client.get("/admin/proofs")).json() if p["task_id"] == task_id
        ][0]["id"]
        assert (
            await admin_client.post(
                f"/admin/proofs/{proof_id}/review", json={"decision": "rejected"}
            )
        ).status_code == 200
        assert (await _submit_url_proof(participant_client, sid, "https://e.com/p3")).status_code == 200
    finally:
        await _cleanup_task(db_session, uuid.UUID(task_id))


async def test_write_without_csrf_header_is_forbidden(participant_client):
    # Authenticated, but drop the CSRF header on a state-changing request.
    participant_client.headers.pop("X-CSRF-Token", None)
    resp = await participant_client.post("/session", json={})
    assert resp.status_code == 403


async def test_non_admin_is_forbidden(participant_client):
    # Cannot create tasks...
    assert (
        await participant_client.post(
            "/tasks", json={"title": "x", "description": "d"}
        )
    ).status_code == 403
    # ...nor touch the admin queue.
    assert (await participant_client.get("/admin/proofs")).status_code == 403


async def test_quality_factor_is_clamped(admin_client, participant_client, db_session):
    task_id = await _make_task(admin_client)
    try:
        sid = (
            await participant_client.post("/session", json={"task_id": task_id})
        ).json()["id"]
        await _submit_url_proof(participant_client, sid, "https://e.com/x")
        proof_id = [
            p for p in (await admin_client.get("/admin/proofs")).json() if p["task_id"] == task_id
        ][0]["id"]

        # quality_factor > 1 is rejected by validation (can't mint points).
        bad = await admin_client.post(
            f"/admin/proofs/{proof_id}/review",
            json={"decision": "verified", "quality_factor": 5},
        )
        assert bad.status_code == 422
    finally:
        await _cleanup_task(db_session, uuid.UUID(task_id))


async def test_admin_cannot_review_own_submission(admin_client, db_session):
    task_id = await _make_task(admin_client)
    try:
        sid = (await admin_client.post("/session", json={"task_id": task_id})).json()["id"]
        await _submit_url_proof(admin_client, sid, "https://e.com/self")
        proof_id = [
            p for p in (await admin_client.get("/admin/proofs")).json() if p["task_id"] == task_id
        ][0]["id"]

        resp = await admin_client.post(
            f"/admin/proofs/{proof_id}/review",
            json={"decision": "verified", "quality_factor": 1},
        )
        assert resp.status_code == 403
    finally:
        await _cleanup_task(db_session, uuid.UUID(task_id))
