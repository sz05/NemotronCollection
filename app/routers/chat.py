"""Session + chat routes (tasks 2.2, 2.4, 2.6), now user-scoped: every
route requires the auth cookie, sessions belong to the logged-in user, and
one user can hold many chats (sidebar lists them via GET /sessions).

Sessions are started against a Task (DESIGN.md §2). Each /chat turn first runs
the relevance guardrail (§3.2) before hitting Nemotron, and schedules the
batched scoring + feedback background job (§3.4) after the reply is returned.
"""

import asyncio
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import get_current_user
from app.models import ChatSession, User
from app.repository import (
    append_turn,
    create_session,
    get_chat_session,
    get_task,
    list_sessions,
)
from app.schemas import (
    ChatRequest,
    ChatResponse,
    ScoreOut,
    SessionCreateRequest,
    SessionDetailOut,
    SessionOut,
    SessionSummaryOut,
)
from app.services.auth import AuthError, decrypt_api_key
from app.services.nemotron import NemotronError, send_chat_message
from app.services.relevance import evaluate
from app.services.scoring import score_and_feedback
from app.state import feedback_question_store

logger = logging.getLogger(__name__)

router = APIRouter()

_OFFTOPIC_MESSAGE = (
    "This doesn't seem closely related to your current task or conversation. "
    "Are you sure you want to continue?"
)


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
    body: SessionCreateRequest | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> SessionOut:
    # Body is optional so an unscoped chat (no task) still works.
    task_id = body.task_id if body else None
    session = await create_session(db, user.id, task_id=task_id)
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


@router.get("/sessions/{session_id}/score", response_model=ScoreOut)
async def get_session_score(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> ScoreOut:
    """Latest live score for the session (§3.4). Refreshed on the scoring
    background job's 3-4 turn boundary; returns 0 until the first batch."""
    session = await _get_owned_session(db, session_id, user)
    return ScoreOut(
        session_id=session.id,
        live_score=session.live_score,
        components=session.score_components or {},
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

    # Relevance guardrail (§3.2): if the session is scoped to a task and the
    # user hasn't already acknowledged going off-topic, embed the query and
    # compare it against the running summary + task. A soft, dismissible
    # warning is returned WITHOUT calling Nemotron or persisting anything.
    task_description = ""
    if session.task_id is not None:
        task = await get_task(db, session.task_id)
        task_description = task.description if task else ""
        if task is not None and not body.acknowledge_offtopic:
            # evaluate() is CPU-bound (embedding) -- keep it off the event loop.
            result = await asyncio.to_thread(
                evaluate, body.message, session.context_summary or "", task.description
            )
            if not result.relevant:
                return ChatResponse(
                    session_id=session.id,
                    reply="",
                    relevance_warning={"score": result.score, "message": _OFFTOPIC_MESSAGE},
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

    # §3.4: batched scoring + feedback, scheduled to run after this response is
    # returned. It no-ops except on the 3-4 turn boundary, so it neither delays
    # the chat reply nor fires a Gemini call every turn.
    background_tasks.add_task(
        score_and_feedback, session.id, task_description, session.messages
    )

    return ChatResponse(session_id=session.id, reply=reply)
