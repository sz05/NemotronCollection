"""Request/response models for the API routes."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class SessionOut(BaseModel):
    id: uuid.UUID


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
