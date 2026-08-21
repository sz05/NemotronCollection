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


def _build_submission_prompt(theme: str | None, user_messages: list[str]) -> str:
    turns = "\n".join(f"- {m}" for m in user_messages) or "(none)"
    if theme:
        criteria = (
            "The user is working toward a THEME/challenge. Judge ONLY the "
            "user's own messages (the assistant's replies are NOT shown). Weigh "
            "two things together:\n"
            "1. COMPLETION -- how far the user's messages actually drive toward "
            "completing the theme.\n"
            "2. APPROACH -- the quality of their prompting: clarity, specificity, "
            "iteration, and how well they direct the assistant.\n\n"
            f"THEME:\n{theme}\n"
        )
    else:
        criteria = (
            "This is a free chat with NO set theme. Judge ONLY whether the user "
            "is asking sensible, coherent, substantive things. Reward genuine, "
            "thoughtful engagement; heavily penalise gibberish, spam, one-word "
            "messages, repetition, or nonsense.\n"
        )
    return (
        "You are a STRICT grader. Grade the user on a 0-100 scale. Be harsh: "
        "most real effort should land in 40-65; reserve 80+ for genuinely "
        "excellent work and 96-100 for the truly exceptional. Bands:\n"
        "- 0-20: gibberish, off-topic, or no real engagement\n"
        "- 21-40: minimal, vague, little substance\n"
        "- 41-60: moderate -- some substance but shallow or incomplete\n"
        "- 61-80: strong -- clear progress and a good approach\n"
        "- 81-95: excellent -- thorough and skilful\n"
        "- 96-100: exceptional (rare)\n\n"
        f"{criteria}\n"
        "Return ONLY a JSON object, no other text, no markdown, no code fences:\n"
        '{"score": int}\n\n'
        f"USER MESSAGES:\n{turns}\n"
    )


async def score_submission(theme: str | None, user_messages: list[str]) -> int:
    """Grade a 'Submit chat' event on 0-100 from the user's messages + theme.

    Themed chats are judged on completion + approach; free chats on sensible,
    non-gibberish engagement. Raises GeminiError on transport/shape failure.
    """
    if not settings.gemini_api_key:
        raise GeminiError("GEMINI_API_KEY is not configured")

    payload = {
        "model": settings.gemini_model,
        "input": _build_submission_prompt(theme, user_messages),
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
        return _clamp_score(parsed["score"])
    except (KeyError, TypeError) as exc:
        raise GeminiError("Gemini submission response missing 'score'") from exc


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
