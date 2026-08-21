"""Request/response models for the API routes."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class SessionOut(BaseModel):
    id: uuid.UUID


class SessionSummaryOut(BaseModel):
    """Sidebar entry: one of the user's chats."""

    id: uuid.UUID
    title: str
    created_at: datetime
    # The task locked to this chat, if any -- lets the picker grey out tasks
    # the user has already taken.
    task_id: uuid.UUID | None = None


class SessionDetailOut(BaseModel):
    id: uuid.UUID
    title: str
    messages: list
    created_at: datetime
    # The locked task's title (the chat's "theme"), or None for a free chat.
    theme: str | None = None


class GoogleLoginRequest(BaseModel):
    credential: str  # Google ID token from the Sign-In button


class DevLoginRequest(BaseModel):
    email: str


class AuthConfigOut(BaseModel):
    google_client_id: str
    dev_auth: bool


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    picture: str
    has_nemotron_key: bool
    is_admin: bool = False
    # Current CSRF token to echo in the X-CSRF-Token header on writes.
    csrf_token: str = ""


class NemotronKeyRequest(BaseModel):
    api_key: str


class ChatRequest(BaseModel):
    session_id: uuid.UUID
    message: str
    acknowledge_offtopic: bool = False


class ChatResponse(BaseModel):
    session_id: uuid.UUID
    reply: str
    # Set when the message is judged off-topic: {"score": float, "message": str}.
    relevance_warning: dict | None = None


class FeedbackQuestionOut(BaseModel):
    question: str | None


class FeedbackRequest(BaseModel):
    session_id: uuid.UUID
    question: str
    answer: str


class FeedbackOut(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    question: str
    answer: str
    created_at: datetime


# --- Tasks ---
class TaskCreate(BaseModel):
    title: str
    description: str
    difficulty: str = "medium"
    base_points: int = 100
    proof_types: list[str] = []
    instructions: str = ""


class TaskOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str
    difficulty: str
    base_points: int
    proof_types: list
    instructions: str
    active: bool


# --- Sessions / scoring ---
class SessionCreateRequest(BaseModel):
    task_id: uuid.UUID | None = None


class ScoreOut(BaseModel):
    session_id: uuid.UUID
    live_score: float
    components: dict


class TotalScoreOut(BaseModel):
    """The user's cumulative score summed across all of their chats."""

    total_score: float


# --- Submit chat (Gemini scoring) ---
class SubmitOut(BaseModel):
    """Result of a 'Submit chat': only the 0-100 score is surfaced to the user.
    points/total_score drive the live UI update but the frontend shows the score."""

    score: int
    points: int
    total_score: int


class SubmitStatusOut(BaseModel):
    """Drives the Submit button. Deliberately does NOT expose how many more
    messages are needed -- the UI shows a generic 'keep chatting' nudge."""

    can_submit: bool
    # Highest score already earned in this chat (None if never submitted).
    best_score: int | None = None


# --- Proof submissions ---
class ProofOut(BaseModel):
    id: uuid.UUID
    status: str
    proof_type: str
    created_at: datetime
    # Populated once reviewed: quality_factor is the fraction (0..1) the admin
    # graded; percent/points are the human-facing derivations of it.
    quality_factor: float | None = None
    percent: int | None = None
    points: int | None = None
    review_notes: str | None = None


# --- Leaderboard ---
class LeaderboardEntryOut(BaseModel):
    rank: int
    user_id: uuid.UUID
    display_name: str
    # total_points = rounded chat_score + bonus_points (the ranking key).
    total_points: int
    chat_score: float
    bonus_points: int
    tasks_completed: int


class LeaderboardOut(BaseModel):
    entries: list[LeaderboardEntryOut]
    me: LeaderboardEntryOut | None = None


# --- Admin review ---
class ReviewRequest(BaseModel):
    decision: str
    # 0..1 fraction of the task's points to award. Clamped so a request can't
    # mint arbitrary points (security finding C2).
    quality_factor: float | None = Field(default=None, ge=0.0, le=1.0)
    notes: str | None = None


class AdminProofOut(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    task_id: uuid.UUID
    user_id: uuid.UUID
    # Denormalized identity/context so the admin UI needn't do N lookups.
    user_email: str = ""
    user_name: str = ""
    task_title: str = ""
    base_points: int = 0
    proof_type: str
    storage_ref: str | None
    has_file: bool = False
    url: str | None
    status: str
    sha256: str | None
    phash: str | None
    quality_factor: float | None = None
    percent: int | None = None
    points: int | None = None
    review_notes: str | None = None
    meta: dict
    created_at: datetime
    reviewed_at: datetime | None = None
