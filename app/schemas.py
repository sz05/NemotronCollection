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


class SessionDetailOut(BaseModel):
    id: uuid.UUID
    title: str
    messages: list
    created_at: datetime


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


class ChatResponse(BaseModel):
    session_id: uuid.UUID
    reply: str


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
