"""Checkpoint 4: submitting an answer creates a FeedbackEntry row that joins
correctly to its ChatSession, and the pending question is cleared server-side
once answered."""

import uuid

from sqlalchemy import delete, select

from app.models import ChatSession, FeedbackEntry
from app.state import feedback_question_store


async def test_feedback_round_trip_and_fk_join(auth_client, db_session):
    session_id = (await auth_client.post("/session")).json()["id"]
    await feedback_question_store.set(uuid.UUID(session_id), "How was that reply?")

    resp = await auth_client.post(
        "/feedback",
        json={
            "session_id": session_id,
            "question": "How was that reply?",
            "answer": "Very clear and concise.",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == session_id
    assert body["answer"] == "Very clear and concise."

    # FK join: feedback_entry.session_id -> chat_session.id resolves.
    row = (
        await db_session.execute(
            select(FeedbackEntry, ChatSession)
            .join(ChatSession, FeedbackEntry.session_id == ChatSession.id)
            .where(FeedbackEntry.session_id == uuid.UUID(session_id))
        )
    ).one()
    feedback_row, session_row = row
    assert feedback_row.answer == "Very clear and concise."
    assert session_row.id == uuid.UUID(session_id)

    # Answering clears the pending question so the panel waits for the next one.
    assert await feedback_question_store.get(uuid.UUID(session_id)) is None

    # cleanup
    await db_session.execute(delete(FeedbackEntry).where(FeedbackEntry.session_id == session_id))
    await db_session.execute(delete(ChatSession).where(ChatSession.id == session_id))
    await db_session.commit()


async def test_feedback_rejects_unknown_session(auth_client):
    resp = await auth_client.post(
        "/feedback",
        json={
            "session_id": "00000000-0000-0000-0000-000000000000",
            "question": "q",
            "answer": "a",
        },
    )
    assert resp.status_code == 404
