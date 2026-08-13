"""Gemini feedback-question client (tasks 3.1, 3.3).

Uses the server-side GEMINI_API_KEY from settings/.env -- unlike Nemotron,
this key is never client-supplied. Builds a prompt from the ongoing chat
context to generate one dynamic feedback question.

Uses the Interactions API (the legacy generateContent endpoint rejects
newer/lightweight models for new API keys as of 2026).
"""

import httpx

from app.config import settings

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"


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

    data = response.json()
    try:
        steps = data["steps"]
        model_output = next(s for s in reversed(steps) if s.get("type") == "model_output")
        text_part = next(c for c in model_output["content"] if c.get("type") == "text")
        return text_part["text"].strip()
    except (KeyError, StopIteration) as exc:
        raise GeminiError("Unexpected Gemini API response shape") from exc
