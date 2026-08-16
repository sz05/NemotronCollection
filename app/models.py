"""Data models (tasks 1.1-1.3).

Per context.md: keep chat logs simple by storing the whole message array in a
single JSONB column rather than a normalized messages table.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    # Naive UTC on purpose: the DB columns below are TIMESTAMP WITHOUT TIME
    # ZONE, and asyncpg rejects mixing aware/naive datetimes in one column.
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(SQLModel, table=True):
    __tablename__ = "app_user"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True),
    )
    # Google's stable account id ("sub" claim). Null for dev-login users.
    google_sub: str | None = Field(default=None, index=True, unique=True)
    email: str = Field(index=True, unique=True)
    name: str = ""
    picture: str = ""
    # Fernet-encrypted Nemotron API key (user opted to store it server-side).
    # Only ever decrypted transiently inside the /chat handler.
    nemotron_key_encrypted: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)


class ChatSession(SQLModel, table=True):
    __tablename__ = "chat_session"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True),
    )
    user_id: uuid.UUID = Field(
        sa_column=Column(UUID(as_uuid=True), ForeignKey("app_user.id"), nullable=False, index=True)
    )
    # Shown in the sidebar; set from the first user message of the chat.
    title: str = "New chat"
    created_at: datetime = Field(default_factory=_utcnow)

    # Task 1.2: JSONB array of {"role": "user"|"assistant", "content": "..."}.
    # Never persist the Nemotron API key here or anywhere else.
    messages: list = Field(default_factory=list, sa_column=Column(JSONB, nullable=False))


class FeedbackEntry(SQLModel, table=True):
    __tablename__ = "feedback_entry"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True),
    )
    session_id: uuid.UUID = Field(
        sa_column=Column(UUID(as_uuid=True), ForeignKey("chat_session.id"), nullable=False)
    )
    question: str
    answer: str
    created_at: datetime = Field(default_factory=_utcnow)
