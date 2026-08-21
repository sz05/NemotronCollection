"""Submit-to-score routes (replaces the old file/URL proof upload).

The user presses "Submit chat"; their OWN messages + the chat's theme are sent
to Gemini, which returns a harsh 0-100 score. Points = score% of the bucket's
ceiling (task.base_points, or free_chat_max_points for a themeless chat). Every
submit is logged in chat_submission; a chat keeps its HIGHEST score, and the
user's total sums that best across all chats.

Unlock gating: submit unlocks after a random(5-8) gap of the user's own
messages, accumulated per submit (e.g. 6 -> 11 -> 19). The gaps are derived
deterministically from the session id so the schedule is stable across reloads
and enforced server-side; the client is never told the exact remaining count.
"""

import hashlib
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.deps import get_current_user
from app.models import User
from app.repository import (
    count_session_submissions,
    create_chat_submission,
    get_chat_session,
    get_task,
    session_best_score,
    user_total_score,
)
from app.schemas import SubmitOut, SubmitStatusOut
from app.services.gemini import GeminiError, score_submission
from app.state import feedback_connection_manager

router = APIRouter()


async def _get_owned_session(db: AsyncSession, session_id: uuid.UUID, user: User):
    session = await get_chat_session(db, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status_code=404, detail=f"ChatSession {session_id} not found")
    return session


def _user_messages(messages: list[dict]) -> list[str]:
    """The user's own message texts (assistant replies are never scored)."""
    return [m["content"] for m in messages if m.get("role") == "user"]


def _next_threshold(session_id: uuid.UUID, submissions_done: int) -> int:
    """User-message count required to unlock the NEXT submit. The threshold is
    the cumulative sum of per-submit gaps; each gap is a stable pseudo-random
    value in [submit_gap_min, submit_gap_max] derived from the session id, so
    the sequence (e.g. 6 -> 11 -> 19) is fixed per chat and can't be gamed."""
    span = settings.submit_gap_max - settings.submit_gap_min + 1
    total = 0
    for i in range(1, submissions_done + 2):  # gaps 1..(done+1)
        digest = hashlib.sha256(f"{session_id}:{i}".encode()).digest()[0]
        total += settings.submit_gap_min + (digest % span)
    return total


@router.get("/sessions/{session_id}/submit-status", response_model=SubmitStatusOut)
async def submit_status(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> SubmitStatusOut:
    session = await _get_owned_session(db, session_id, user)
    count = len(_user_messages(session.messages))
    done = await count_session_submissions(db, session.id)
    threshold = _next_threshold(session.id, done)
    best = await session_best_score(db, session.id)
    return SubmitStatusOut(can_submit=count >= threshold, best_score=best)


@router.post("/sessions/{session_id}/submit", response_model=SubmitOut)
async def submit_chat(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> SubmitOut:
    session = await _get_owned_session(db, session_id, user)
    user_msgs = _user_messages(session.messages)
    count = len(user_msgs)

    done = await count_session_submissions(db, session.id)
    threshold = _next_threshold(session.id, done)
    if count < threshold:
        # Generic nudge -- never reveal how many more messages are needed.
        raise HTTPException(
            status_code=409,
            detail="Keep chatting to unlock -- explore the theme more, then submit.",
        )

    # Theme + points ceiling: the task's description/base_points, or a free chat.
    theme: str | None = None
    ceiling = settings.free_chat_max_points
    if session.task_id is not None:
        task = await get_task(db, session.task_id)
        if task is not None:
            theme = task.description
            ceiling = task.base_points

    try:
        score = await score_submission(theme, user_msgs)
    except GeminiError as exc:
        raise HTTPException(status_code=502, detail=f"Scoring failed: {exc}") from exc

    points = round(score / 100 * ceiling)
    await create_chat_submission(
        db,
        session_id=session.id,
        user_id=user.id,
        task_id=session.task_id,
        score=score,
        points=points,
        user_msg_count=count,
    )

    # Keep-highest is handled by user_total_score (max per chat), so a lower
    # resubmission never reduces the total. Push it live so ScorePanel updates.
    total = await user_total_score(db, user.id)
    await feedback_connection_manager.push_score(session.id, total)

    return SubmitOut(score=score, points=points, total_score=total)
