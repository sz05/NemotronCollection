"""Off-topic detection for chat turns.

Compares the user's query against the running conversation summary and the
task description via embeddings. Fails open (relevant=True) when embeddings
are unavailable so a missing/optional dependency never blocks the user.
"""

from dataclasses import dataclass

from app.config import settings
from app.services.embeddings import cosine, embed


@dataclass
class RelevanceResult:
    relevant: bool
    score: float


def evaluate(query: str, summary: str, task_description: str) -> RelevanceResult:
    """Score how on-topic `query` is relative to summary/task; fail-open."""
    q_vec = embed(query)
    if q_vec is None:
        # Embeddings unavailable -> soft warning, treat as relevant.
        return RelevanceResult(relevant=True, score=1.0)

    summary_vec = embed(summary)
    task_vec = embed(task_description)
    if summary_vec is None and task_vec is None:
        return RelevanceResult(relevant=True, score=1.0)

    score = 0.0
    if summary_vec is not None:
        score = max(score, cosine(q_vec, summary_vec))
    if task_vec is not None:
        score = max(score, cosine(q_vec, task_vec))

    return RelevanceResult(relevant=score >= settings.relevance_threshold, score=score)
