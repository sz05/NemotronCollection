"""Data models (tasks 1.1-1.3).

Per context.md: keep chat logs simple by storing the whole message array in a
single JSONB column rather than a normalized messages table.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, ForeignKey, UniqueConstraint
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
    # Gamification profile fields.
    display_name: str = ""
    disqualified: bool = False
    created_at: datetime = Field(default_factory=_utcnow)


class Task(SQLModel, table=True):
    __tablename__ = "task"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True),
    )
    title: str
    description: str
    difficulty: str = "medium"
    base_points: int = 100
    # Allowed proof kinds for this task, e.g. ["image", "url", "text"].
    proof_types: list = Field(default_factory=list, sa_column=Column(JSONB, nullable=False))
    instructions: str = ""
    active: bool = True
    created_by: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(UUID(as_uuid=True), ForeignKey("app_user.id"), nullable=True),
    )
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

    # Optional link to the task this session is working toward.
    task_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(UUID(as_uuid=True), ForeignKey("task.id"), nullable=True, index=True),
    )
    # Rolling summary + live scoring maintained by the scoring service.
    context_summary: str = ""
    live_score: float = 0.0
    score_components: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))


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
    # Snapshot of the conversation (same shape as ChatSession.messages) at
    # the moment the feedback question was generated -- so postprocessing
    # can pair each answer with exactly the exchange it judged, even if the
    # chat continued afterwards.
    chat_context: list = Field(default_factory=list, sa_column=Column(JSONB, nullable=False))
    created_at: datetime = Field(default_factory=_utcnow)


class ScoreEvent(SQLModel, table=True):
    __tablename__ = "score_event"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True),
    )
    session_id: uuid.UUID = Field(
        sa_column=Column(UUID(as_uuid=True), ForeignKey("chat_session.id"), nullable=False)
    )
    turn_index: int
    responsiveness: float
    elaboration: float
    development: float
    progress: float
    live_score: float
    # Snapshot of the messages window that produced this score.
    context_snapshot: list = Field(default_factory=list, sa_column=Column(JSONB, nullable=False))
    created_at: datetime = Field(default_factory=_utcnow)


class ProofSubmission(SQLModel, table=True):
    __tablename__ = "proof_submission"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True),
    )
    session_id: uuid.UUID = Field(
        sa_column=Column(UUID(as_uuid=True), ForeignKey("chat_session.id"), nullable=False)
    )
    task_id: uuid.UUID = Field(
        sa_column=Column(UUID(as_uuid=True), ForeignKey("task.id"), nullable=False)
    )
    user_id: uuid.UUID = Field(
        sa_column=Column(UUID(as_uuid=True), ForeignKey("app_user.id"), nullable=False)
    )
    proof_type: str
    storage_ref: str | None = None
    url: str | None = None
    sha256: str | None = None
    phash: str | None = None
    meta: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    status: str = "pending"
    reviewer_id: uuid.UUID | None = Field(
        default=None, sa_column=Column(UUID(as_uuid=True), nullable=True)
    )
    review_notes: str | None = None
    quality_factor: float | None = None
    warning_ack_at: datetime | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    reviewed_at: datetime | None = None


class PointAward(SQLModel, table=True):
    __tablename__ = "point_award"
    __table_args__ = (UniqueConstraint("user_id", "task_id"),)

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True),
    )
    user_id: uuid.UUID = Field(
        sa_column=Column(UUID(as_uuid=True), ForeignKey("app_user.id"), nullable=False)
    )
    task_id: uuid.UUID = Field(
        sa_column=Column(UUID(as_uuid=True), ForeignKey("task.id"), nullable=False)
    )
    proof_id: uuid.UUID = Field(
        sa_column=Column(UUID(as_uuid=True), ForeignKey("proof_submission.id"), nullable=False)
    )
    points: int
    created_at: datetime = Field(default_factory=_utcnow)


class ChatSubmission(SQLModel, table=True):
    """One 'Submit chat' event: the user's messages + theme were scored by
    Gemini. Every submit is logged (audit + drives the next unlock threshold);
    a chat's effective points is the MAX across its submissions (keep-highest),
    and a user's total is the sum of that max across all their chats."""

    __tablename__ = "chat_submission"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True),
    )
    session_id: uuid.UUID = Field(
        sa_column=Column(UUID(as_uuid=True), ForeignKey("chat_session.id"), nullable=False, index=True)
    )
    user_id: uuid.UUID = Field(
        sa_column=Column(UUID(as_uuid=True), ForeignKey("app_user.id"), nullable=False, index=True)
    )
    # Null for a free (themeless) chat, which is scored on sensible engagement.
    task_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(UUID(as_uuid=True), ForeignKey("task.id"), nullable=True),
    )
    # Raw Gemini grade 0-100 and the points it converts to (score% of the
    # bucket's ceiling: task.base_points, or free_chat_max_points for a free chat).
    score: int
    points: int
    # User-message count at submit time (audit / threshold context).
    user_msg_count: int
    created_at: datetime = Field(default_factory=_utcnow)
