"""Repository/service functions (task 1.5).

Thin async wrappers around the DB session so route handlers (Phase 2-4)
don't touch SQLAlchemy directly.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChatSession, FeedbackEntry, User


async def get_or_create_google_user(
    db: AsyncSession, google_sub: str, email: str, name: str, picture: str
) -> User:
    result = await db.execute(select(User).where(User.google_sub == google_sub))
    user = result.scalar_one_or_none()
    if user is None:
        # Same email may exist from a dev-login session; claim it.
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(google_sub=google_sub, email=email, name=name, picture=picture)
        else:
            user.google_sub = google_sub
    user.name = name or user.name
    user.picture = picture or user.picture
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def get_or_create_dev_user(db: AsyncSession, email: str) -> User:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(email=email, name=email.split("@")[0])
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user


async def set_user_nemotron_key(db: AsyncSession, user: User, encrypted: str | None) -> User:
    user.nemotron_key_encrypted = encrypted
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def create_session(db: AsyncSession, user_id: uuid.UUID) -> ChatSession:
    session = ChatSession(user_id=user_id, messages=[])
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def list_sessions(db: AsyncSession, user_id: uuid.UUID) -> list[ChatSession]:
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.user_id == user_id)
        .order_by(ChatSession.created_at.desc())
    )
    return list(result.scalars().all())


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

    if not session.messages:
        # First turn names the chat for the sidebar.
        session.title = user_content[:60]

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
