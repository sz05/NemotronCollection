"""Gemini feedback-question client (tasks 3.1, 3.3).

Uses the server-side GEMINI_API_KEY from settings/.env -- unlike Nemotron,
this key is never client-supplied. Builds a prompt from the ongoing chat
context to generate one dynamic feedback question.

Uses the Interactions API (the legacy generateContent endpoint rejects
newer/lightweight models for new API keys as of 2026).
"""

import json

import httpx

from app.config import settings

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"

# Live-scoring rubric weights (must sum to 100). See DESIGN.md.
_RUBRIC_WEIGHTS = {
    "responsiveness": 30,
    "elaboration": 25,
    "development": 25,
    "progress": 20,
}


class GeminiError(RuntimeError):
    """Raised when the Gemini API call fails."""


def _build_prompt(messages: list[dict]) -> str:
    transcript = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
    return (
        "You are observing a chat between a user and an AI assistant. Based "
        "on the conversation so far, write ONE short, specific feedback "
        "question to ask the user about their experience with the "
        "assistant's latest reply. Return only the question text, nothing "
        "else -- no quotes, no preamble.\n\n"
        f"Conversation so far:\n{transcript}"
    )


async def generate_feedback_question(messages: list[dict]) -> str:
    """Task 3.3: pass the ongoing chat context to Gemini and return one
    dynamic feedback question."""
    if not settings.gemini_api_key:
        raise GeminiError("GEMINI_API_KEY is not configured")

    payload = {"model": settings.gemini_model, "input": _build_prompt(messages)}
    headers = {"x-goog-api-key": settings.gemini_api_key}

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(GEMINI_ENDPOINT, headers=headers, json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # exc.response.text is safe to include -- it's Google's error body,
            # never echoes the key back.
            raise GeminiError(
                f"Gemini API returned {exc.response.status_code}: {exc.response.text[:500]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise GeminiError("Gemini API request failed") from exc

    return _extract_text(response.json())


def _extract_text(data: dict) -> str:
    """Pull the last model-output text part from an Interactions API response."""
    try:
        steps = data["steps"]
        model_output = next(s for s in reversed(steps) if s.get("type") == "model_output")
        text_part = next(c for c in model_output["content"] if c.get("type") == "text")
        return text_part["text"].strip()
    except (KeyError, StopIteration) as exc:
        raise GeminiError("Unexpected Gemini API response shape") from exc


def _clamp_score(value: object) -> int:
    """Coerce a model-emitted score to an int in [0, 100]. Raises on garbage."""
    try:
        num = int(round(float(value)))
    except (TypeError, ValueError) as exc:
        raise GeminiError("Gemini returned a non-numeric score") from exc
    return max(0, min(100, num))


def _build_scoring_prompt(context: dict) -> str:
    task = context.get("task", "")
    summary = context.get("summary", "")
    recent_user = context.get("recent_user", []) or []
    recent_llm = context.get("recent_llm", []) or []

    user_block = "\n".join(f"- {c}" for c in recent_user) or "(none)"
    llm_block = "\n".join(f"- {c}" for c in recent_llm) or "(none)"

    return (
        "You are a strict grader evaluating a user's progress on a task while "
        "they converse with an AI assistant. Score the USER's recent "
        "contributions on four dimensions, each 0-100, per this rubric "
        "(weights shown for context only -- return each raw 0-100 score):\n"
        f"- responsiveness ({_RUBRIC_WEIGHTS['responsiveness']}%): how directly "
        "the user engages with the assistant's replies and the task.\n"
        f"- elaboration ({_RUBRIC_WEIGHTS['elaboration']}%): depth, detail, and "
        "specificity the user adds.\n"
        f"- development ({_RUBRIC_WEIGHTS['development']}%): how the user builds "
        "on prior turns and advances ideas.\n"
        f"- progress ({_RUBRIC_WEIGHTS['progress']}%): concrete movement toward "
        "completing the task.\n\n"
        "Also produce an UPDATED running summary of the conversation (2-4 "
        "sentences, third person) and ONE short, specific feedback question to "
        "nudge the user forward.\n\n"
        "Return ONLY a JSON object with exactly these keys and no other text, "
        "no markdown, no code fences:\n"
        '{"updated_summary": str, "scores": {"responsiveness": int, '
        '"elaboration": int, "development": int, "progress": int}, '
        '"feedback_question": str}\n\n'
        f"TASK:\n{task}\n\n"
        f"PREVIOUS SUMMARY:\n{summary or '(none yet)'}\n\n"
        f"RECENT USER TURNS:\n{user_block}\n\n"
        f"RECENT ASSISTANT TURNS:\n{llm_block}\n"
    )


def _parse_scoring_json(text: str) -> dict:
    """Parse the model's JSON reply, tolerating stray fences/prose."""
    stripped = text.strip()
    # Tolerate ```json ... ``` fences and any leading/trailing prose.
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise GeminiError("Gemini scoring response was not JSON")
    try:
        return json.loads(stripped[start : end + 1])
    except json.JSONDecodeError as exc:
        raise GeminiError("Gemini scoring response was not valid JSON") from exc


async def score_and_summarize(context: dict) -> dict:
    """Score the user's recent turns, refresh the running summary, and emit one
    feedback question in a single Gemini call.

    ``context`` is the dict produced by
    ``app.services.context_window.build_scoring_context`` (keys: ``task``,
    ``summary``, ``recent_user``, ``recent_llm``). Returns::

        {"updated_summary": str,
         "scores": {"responsiveness": int, "elaboration": int,
                    "development": int, "progress": int},
         "feedback_question": str}

    Raises :class:`GeminiError` on any transport or shape failure so the caller
    can degrade gracefully.
    """
    if not settings.gemini_api_key:
        raise GeminiError("GEMINI_API_KEY is not configured")

    payload = {
        "model": settings.gemini_model,
        "input": _build_scoring_prompt(context),
    }
    headers = {"x-goog-api-key": settings.gemini_api_key}

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(GEMINI_ENDPOINT, headers=headers, json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise GeminiError(
                f"Gemini API returned {exc.response.status_code}: {exc.response.text[:500]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise GeminiError("Gemini API request failed") from exc

    parsed = _parse_scoring_json(_extract_text(response.json()))

    try:
        raw_scores = parsed["scores"]
        scores = {dim: _clamp_score(raw_scores[dim]) for dim in _RUBRIC_WEIGHTS}
        updated_summary = str(parsed["updated_summary"]).strip()
        feedback_question = str(parsed["feedback_question"]).strip()
    except (KeyError, TypeError) as exc:
        raise GeminiError("Gemini scoring response missing required fields") from exc

    if not feedback_question:
        raise GeminiError("Gemini returned an empty feedback question")

    return {
        "updated_summary": updated_summary,
        "scores": scores,
        "feedback_question": feedback_question,
    }
