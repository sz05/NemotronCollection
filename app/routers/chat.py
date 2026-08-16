"""Session + chat routes (tasks 2.2, 2.4, 2.6), now user-scoped: every
route requires the auth cookie, sessions belong to the logged-in user, and
one user can hold many chats (sidebar lists them via GET /sessions)."""

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import get_current_user
from app.models import ChatSession, User
from app.repository import append_turn, create_session, get_chat_session, list_sessions
from app.schemas import (
    ChatRequest,
    ChatResponse,
    SessionDetailOut,
    SessionOut,
    SessionSummaryOut,
)
from app.services.auth import AuthError, decrypt_api_key
from app.services.gemini import GeminiError, generate_feedback_question
from app.services.nemotron import NemotronError, send_chat_message
from app.state import feedback_connection_manager, feedback_question_store

logger = logging.getLogger(__name__)

router = APIRouter()


async def _generate_and_store_feedback_question(session_id: uuid.UUID, messages: list[dict]) -> None:
    """Task 3.2 payload: runs after the /chat response has been sent, so it
    never adds latency to the active chat stream."""
    try:
        question = await generate_feedback_question(messages)
    except GeminiError as exc:
        logger.warning("Gemini feedback question generation failed for %s: %s", session_id, exc)
        return
    # Keep the conversation snapshot the question was generated from; it is
    # persisted onto the feedback_entry row when the user answers.
    await feedback_question_store.set(session_id, question, context=messages)
    # Push it straight to any connected side panel -- no client polling.
    await feedback_connection_manager.push(session_id, question)


async def _get_owned_session(
    db: AsyncSession, session_id: uuid.UUID, user: User
) -> ChatSession:
    session = await get_chat_session(db, session_id)
    if session is None or session.user_id != user.id:
        # 404 (not 403) for foreign sessions: don't reveal they exist.
        raise HTTPException(status_code=404, detail=f"ChatSession {session_id} not found")
    return session


@router.post("/session", response_model=SessionOut)
async def create_chat_session(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)
) -> SessionOut:
    session = await create_session(db, user.id)
    return SessionOut(id=session.id)


@router.get("/sessions", response_model=list[SessionSummaryOut])
async def list_chat_sessions(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)
) -> list[SessionSummaryOut]:
    sessions = await list_sessions(db, user.id)
    return [
        SessionSummaryOut(id=s.id, title=s.title, created_at=s.created_at) for s in sessions
    ]


@router.get("/sessions/{session_id}", response_model=SessionDetailOut)
async def get_chat_session_detail(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> SessionDetailOut:
    session = await _get_owned_session(db, session_id, user)
    return SessionDetailOut(
        id=session.id,
        title=session.title,
        messages=session.messages,
        created_at=session.created_at,
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    background_tasks: BackgroundTasks,
    x_nemotron_key: str | None = Header(default=None, alias="X-Nemotron-Key"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> ChatResponse:
    session = await _get_owned_session(db, body.session_id, user)

    # Key resolution: an explicit header wins (lets a user try a different
    # key without saving it); otherwise decrypt the one stored on the user.
    # Either way it lives only in this request's locals and is never logged.
    api_key = x_nemotron_key
    if not api_key:
        if not user.nemotron_key_encrypted:
            raise HTTPException(
                status_code=401, detail="No Nemotron API key on file -- save one first"
            )
        try:
            api_key = decrypt_api_key(user.nemotron_key_encrypted)
        except AuthError as exc:
            raise HTTPException(
                status_code=401, detail="Stored API key is unreadable -- re-enter it"
            ) from exc

    # A pending feedback question blocks the next chat turn: the user must
    # answer it (POST /feedback clears the store) before chatting again.
    # Enforced here so the rule holds even for clients that bypass the UI.
    if await feedback_question_store.get(body.session_id):
        raise HTTPException(
            status_code=409,
            detail="Answer the pending feedback question before sending a new message",
        )

    # Task 2.6: the user's turn is NOT persisted yet here -- only sent to
    # Nemotron as part of the wire history. If the call fails, nothing is
    # written, so a retry doesn't resend a malformed history with a
    # dangling, unanswered user turn.
    wire_messages = [*session.messages, {"role": "user", "content": body.message}]

    try:
        reply = await send_chat_message(api_key, wire_messages)
    except NemotronError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    session = await append_turn(db, body.session_id, body.message, reply)

    # Task 3.2: scheduled to run after this response is returned to the
    # client -- does not delay the chat reply.
    background_tasks.add_task(_generate_and_store_feedback_question, session.id, session.messages)

    return ChatResponse(session_id=session.id, reply=reply)
