"""Repository/service functions (task 1.5).

Thin async wrappers around the DB session so route handlers (Phase 2-4)
don't touch SQLAlchemy directly.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChatSession, FeedbackEntry


async def create_session(db: AsyncSession) -> ChatSession:
    session = ChatSession(messages=[])
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def append_message(db: AsyncSession, session_id: uuid.UUID, role: str, content: str) -> ChatSession:
    session = await db.get(ChatSession, session_id)
    if session is None:
        raise ValueError(f"ChatSession {session_id} not found")

    # Reassign (rather than .append) so SQLAlchemy's change tracking on the
    # JSONB column reliably detects the mutation and includes it in the UPDATE.
    session.messages = [*session.messages, {"role": role, "content": content}]

    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def get_chat_session(db: AsyncSession, session_id: uuid.UUID) -> ChatSession | None:
    return await db.get(ChatSession, session_id)


async def append_turn(
    db: AsyncSession, session_id: uuid.UUID, user_content: str, assistant_content: str
) -> ChatSession:
    """Persist a completed user+assistant round trip atomically. Used instead
    of two append_message calls so a failed Nemotron call (see the /chat
    handler) never leaves a dangling, unanswered user turn in history --
    that malformed shape (consecutive user turns) got resent to the model on
    every retry and appeared to make it far slower/less reliable."""
    session = await db.get(ChatSession, session_id)
    if session is None:
        raise ValueError(f"ChatSession {session_id} not found")

    session.messages = [
        *session.messages,
        {"role": "user", "content": user_content},
        {"role": "assistant", "content": assistant_content},
    ]

    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def save_feedback(
    db: AsyncSession, session_id: uuid.UUID, question: str, answer: str
) -> FeedbackEntry:
    entry = FeedbackEntry(session_id=session_id, question=question, answer=answer)
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry
