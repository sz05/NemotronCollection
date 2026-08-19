"""Builds the compact context payload passed to Gemini scoring.

Keeps only the task, the running summary, and a sliding window of the most
recent user/assistant turns to bound token usage.
"""

from app.config import settings


def build_scoring_context(
    task_description: str, summary: str, messages: list[dict]
) -> dict:
    """Assemble the scoring context from task, summary, and recent turns.

    `messages` is a chronological list of {"role": ..., "content": ...} dicts;
    roles other than user/assistant (e.g. system) are ignored.
    """
    user_contents = [
        m.get("content", "") for m in messages if m.get("role") == "user"
    ]
    llm_contents = [
        m.get("content", "") for m in messages if m.get("role") == "assistant"
    ]

    return {
        "task": task_description,
        "summary": summary,
        "recent_user": user_contents[-settings.window_user_turns :],
        "recent_llm": llm_contents[-settings.window_llm_turns :],
    }
