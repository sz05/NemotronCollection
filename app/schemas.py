"""Request/response models for the API routes."""

import uuid
from datetime import datetime

from pydantic import BaseModel


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


# --- Proof submissions ---
class ProofOut(BaseModel):
    id: uuid.UUID
    status: str
    proof_type: str
    created_at: datetime


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
    quality_factor: float | None = None
    notes: str | None = None


class AdminProofOut(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    task_id: uuid.UUID
    user_id: uuid.UUID
    proof_type: str
    storage_ref: str | None
    url: str | None
    status: str
    sha256: str | None
    phash: str | None
    meta: dict
    created_at: datetime
