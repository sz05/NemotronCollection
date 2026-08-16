"""Feedback routes: live question push over WebSocket (task 3.4), a GET
fallback for polling/debugging, and answer persistence (task 4.2, using
repository.save_feedback from task 1.5)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session_factory, get_session
from app.deps import get_current_user
from app.models import User
from app.repository import get_chat_session, save_feedback
from app.schemas import FeedbackOut, FeedbackQuestionOut, FeedbackRequest
from app.services.auth import AUTH_COOKIE_NAME, AuthError, decode_session_token
from app.state import feedback_connection_manager, feedback_question_store

router = APIRouter()


@router.websocket("/ws/feedback/{session_id}")
async def feedback_ws(websocket: WebSocket, session_id: uuid.UUID) -> None:
    """Task 3.4 (WS variant): the side panel connects once per session and
    receives questions pushed the moment the background Gemini task (task
    3.2) finishes -- no client polling."""
    # The browser sends the auth cookie on the WS handshake; only the
    # session's owner may listen for its feedback questions.
    token = websocket.cookies.get(AUTH_COOKIE_NAME)
    try:
        user_id = decode_session_token(token) if token else None
    except AuthError:
        user_id = None
    if user_id is None:
        await websocket.close(code=4401)
        return
    async with async_session_factory() as db:
        chat_session = await get_chat_session(db, session_id)
    if chat_session is None or chat_session.user_id != user_id:
        await websocket.close(code=4404)
        return

    await feedback_connection_manager.connect(session_id, websocket)
    try:
        # Catch the panel up immediately if a question was already generated
        # before this connection was opened (e.g. on reconnect/reload).
        current = await feedback_question_store.get(session_id)
        if current:
            await websocket.send_json({"question": current})

        while True:
            # The panel doesn't send anything meaningful; this just keeps
            # the connection open and detects disconnects.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await feedback_connection_manager.disconnect(session_id, websocket)


@router.get("/feedback-question/{session_id}", response_model=FeedbackQuestionOut)
async def get_feedback_question(session_id: uuid.UUID) -> FeedbackQuestionOut:
    """Fallback/debug read -- the frontend uses the WebSocket above; this
    stays for tooling, tests, and clients that can't hold a socket open."""
    question = await feedback_question_store.get(session_id)
    return FeedbackQuestionOut(question=question)


@router.post("/feedback", response_model=FeedbackOut)
async def submit_feedback(
    body: FeedbackRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> FeedbackOut:
    chat_session = await get_chat_session(db, body.session_id)
    if chat_session is None or chat_session.user_id != user.id:
        raise HTTPException(status_code=404, detail="Unknown session_id")

    chat_context = await feedback_question_store.get_context(body.session_id)

    try:
        entry = await save_feedback(
            db, body.session_id, body.question, body.answer, chat_context
        )
    except IntegrityError as exc:  # FK violation if session_id doesn't exist
        await db.rollback()
        raise HTTPException(status_code=404, detail="Unknown session_id") from exc

    # Task 4.1 support: once answered, clear the pending question so the
    # side panel goes back to "waiting" until the next chat turn generates
    # a fresh one.
    await feedback_question_store.clear(body.session_id)

    return FeedbackOut(
        id=entry.id,
        session_id=entry.session_id,
        question=entry.question,
        answer=entry.answer,
        created_at=entry.created_at,
    )
