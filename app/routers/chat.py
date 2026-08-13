"""Session + chat routes (tasks 2.2, 2.4, 2.6, and the session-creation
endpoint needed to hand the frontend a session_id before the first turn)."""

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.repository import append_turn, create_session, get_chat_session
from app.schemas import ChatRequest, ChatResponse, SessionOut
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
    await feedback_question_store.set(session_id, question)
    # Push it straight to any connected side panel -- no client polling.
    await feedback_connection_manager.push(session_id, question)


@router.post("/session", response_model=SessionOut)
async def create_chat_session(db: AsyncSession = Depends(get_session)) -> SessionOut:
    session = await create_session(db)
    return SessionOut(id=session.id)


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    background_tasks: BackgroundTasks,
    x_nemotron_key: str = Header(..., alias="X-Nemotron-Key"),
    db: AsyncSession = Depends(get_session),
) -> ChatResponse:
    # Task 2.2: the key lives only in this request's local variable/header --
    # it is never written to a log statement, a DB column, or a module-level
    # variable. It is passed straight through to the Nemotron client below.
    if not x_nemotron_key:
        raise HTTPException(status_code=401, detail="Missing X-Nemotron-Key header")

    session = await get_chat_session(db, body.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"ChatSession {body.session_id} not found")

    # Task 2.6: the user's turn is NOT persisted yet here -- only sent to
    # Nemotron as part of the wire history. If the call fails, nothing is
    # written, so a retry doesn't resend a malformed history with a
    # dangling, unanswered user turn (that previously made the model
    # noticeably slower/less reliable on retries).
    wire_messages = [*session.messages, {"role": "user", "content": body.message}]

    try:
        reply = await send_chat_message(x_nemotron_key, wire_messages)
    except NemotronError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    session = await append_turn(db, body.session_id, body.message, reply)

    # Task 3.2: scheduled to run after this response is returned to the
    # client -- does not delay the chat reply.
    background_tasks.add_task(_generate_and_store_feedback_question, session.id, session.messages)

    return ChatResponse(session_id=session.id, reply=reply)
