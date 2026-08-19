"""Batched live-scoring + feedback background task (DESIGN.md §3.4).

Runs after a /chat response is returned. Only once every
``settings.score_interval_turns`` turns does it call Gemini to (re)score the
conversation, refresh the running summary, and generate one feedback question --
all in a single call. Any failure is logged and swallowed so the background task
never crashes and the prior summary/score are preserved.
"""

import logging
import uuid

from app.config import settings
from app.db import async_session_factory
from app.repository import add_score_event, get_chat_session, update_session_score
from app.services.context_window import build_scoring_context
from app.services.gemini import GeminiError, score_and_summarize
from app.state import feedback_connection_manager, feedback_question_store

logger = logging.getLogger(__name__)

# LiveScore = 0.30R + 0.25E + 0.25D + 0.20P
_RUBRIC = {
    "responsiveness": 0.30,
    "elaboration": 0.25,
    "development": 0.25,
    "progress": 0.20,
}


def _live_score(scores: dict) -> float:
    return round(sum(float(scores.get(dim, 0.0)) * w for dim, w in _RUBRIC.items()), 2)


async def score_and_feedback(
    session_id: uuid.UUID, task_description: str, messages: list[dict]
) -> None:
    """Score the batch and push a fresh feedback question -- but only on the
    3-4 turn boundary. One completed turn == one user + one assistant message."""
    turn_index = len(messages) // 2
    if turn_index == 0 or turn_index % settings.score_interval_turns != 0:
        return

    try:
        async with async_session_factory() as db:
            session = await get_chat_session(db, session_id)
            prior_summary = session.context_summary if session else ""

        context = build_scoring_context(task_description, prior_summary or "", messages)
        result = await score_and_summarize(context)

        scores = result["scores"]
        live = _live_score(scores)
        # §8.2 guard: only overwrite the summary when the model returned a
        # non-empty one -- a bad summary has downstream blast radius.
        summary = result.get("updated_summary") or prior_summary or ""
        question = (result.get("feedback_question") or "").strip()

        async with async_session_factory() as db:
            await update_session_score(db, session_id, summary, scores, live)
            await add_score_event(
                db,
                session_id,
                turn_index,
                {**scores, "context_snapshot": messages},
                live,
            )
    except GeminiError as exc:
        # Expected, best-effort: keep the prior summary/score, retry next batch.
        logger.warning("Scoring skipped for %s: %s", session_id, exc)
        return
    except Exception:  # noqa: BLE001 -- a background task must never crash the loop
        logger.exception("Unexpected scoring failure for %s", session_id)
        return

    if question:
        await feedback_question_store.set(session_id, question, context=messages)
        await feedback_connection_manager.push(session_id, question)
