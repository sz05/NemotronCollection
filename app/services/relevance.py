"""Off-topic detection for chat turns.

Compares the user's query against the running conversation summary and the
task description via embeddings. Fails open (relevant=True) when embeddings
are unavailable so a missing/optional dependency never blocks the user.

A single-vector embedding of the whole query averages every clause together,
so implementation boilerplate ("give file structure, then code file by file")
dilutes the one on-topic clause ("make a BookMyShow clone") and the cosine
collapses below the threshold -- a false off-topic warning. To counter this we
split the query into clauses, embed each, and take the *max* similarity across
clause x anchor: an on-topic clause scores on its own merits instead of being
drowned by the rest of the sentence.
"""

import re
from dataclasses import dataclass

from app.config import settings
from app.services.embeddings import cosine, embed

# Clause boundaries: punctuation plus a few conjunctions/prepositions that
# typically separate an intent ("make a bookmyshow clone") from a directive
# ("using fastapi", "give file structure").
_CHUNK_SPLIT = re.compile(
    r"[,.;:!?\n]|\band\b|\bthen\b|\busing\b|\bwith\b|\bbut\b|\bso\b",
    re.IGNORECASE,
)


def _chunks(text: str) -> list[str]:
    """Clause-like fragments of `text`, plus the whole string as a fallback so
    a short, un-splittable message is still scored."""
    parts = [p.strip() for p in _CHUNK_SPLIT.split(text)]
    chunks = [p for p in parts if len(p) > 2]
    whole = text.strip()
    if whole and whole not in chunks:
        chunks.append(whole)
    return chunks


@dataclass
class RelevanceResult:
    relevant: bool
    score: float


def evaluate(query: str, summary: str, task_description: str) -> RelevanceResult:
    """Score how on-topic `query` is relative to summary/task; fail-open.

    score = max over (query clause, anchor) of cosine, where anchors are the
    running summary and the task description.
    """
    # summary + task_description repeat across turns -- cache them so only the
    # unique query clauses are encoded fresh each turn.
    anchors = [
        vec
        for vec in (embed(summary, cache=True), embed(task_description, cache=True))
        if vec is not None
    ]
    if not anchors:
        # No anchor to compare against -> treat as relevant.
        return RelevanceResult(relevant=True, score=1.0)

    chunk_vecs = [vec for vec in (embed(c) for c in _chunks(query)) if vec is not None]
    if not chunk_vecs:
        # Embeddings unavailable for the query -> soft warning, treat relevant.
        return RelevanceResult(relevant=True, score=1.0)

    score = max(cosine(cv, av) for cv in chunk_vecs for av in anchors)
    return RelevanceResult(relevant=score >= settings.relevance_threshold, score=score)
