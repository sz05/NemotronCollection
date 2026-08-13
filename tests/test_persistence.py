"""Checkpoint 1: migration applies cleanly; a session + message + feedback
row can be inserted and read back correctly, with FK linkage intact."""

from sqlalchemy import delete

from app.models import ChatSession, FeedbackEntry
from app.repository import append_message, create_session, save_feedback


async def test_session_message_and_feedback_round_trip(db_session):
    session = await create_session(db_session)
    assert session.id is not None
    assert session.messages == []

    session = await append_message(db_session, session.id, "user", "hello")
    session = await append_message(db_session, session.id, "assistant", "hi there")
    assert session.messages == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]

    feedback = await save_feedback(
        db_session, session.id, "What made this reply useful?", "It was concise."
    )
    assert feedback.session_id == session.id
    assert feedback.question == "What made this reply useful?"
    assert feedback.answer == "It was concise."

    # cleanup (FK requires feedback rows removed before their session)
    await db_session.execute(delete(FeedbackEntry).where(FeedbackEntry.session_id == session.id))
    await db_session.execute(delete(ChatSession).where(ChatSession.id == session.id))
    await db_session.commit()
