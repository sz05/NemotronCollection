"""Sentence embedding helpers for semantic relevance + scoring.

Heavy deps (sentence_transformers/torch) are imported lazily inside functions
so importing this module never fails when they are absent. The model is loaded
once and cached in a module-level singleton; any load failure yields None so
callers can fail open.
"""

import math
from functools import lru_cache

from app.config import settings

# Singleton model + a flag so we only attempt (and log) the load once.
_model = None
_load_failed = False


def _get_model():
    """Lazily load and cache the SentenceTransformer, or None if unavailable."""
    global _model, _load_failed
    if _model is not None:
        return _model
    if _load_failed:
        return None
    try:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(settings.embedding_model)
        return _model
    except Exception:
        # Missing dep, no network for model download, incompatible torch, etc.
        _load_failed = True
        return None


def warmup() -> bool:
    """Force the (otherwise lazy) model load + one tiny encode so the FIRST
    real /chat request doesn't pay the multi-second cold start. Safe to call
    from app startup; returns True once the model is ready."""
    model = _get_model()
    if model is None:
        return False
    try:
        model.encode("warmup", convert_to_numpy=True)
        return True
    except Exception:
        return False


def _encode(text: str) -> list[float] | None:
    model = _get_model()
    if model is None:
        return None
    try:
        vec = model.encode(text, convert_to_numpy=True, normalize_embeddings=False)
        return [float(x) for x in vec.tolist()]
    except Exception:
        return None


@lru_cache(maxsize=1024)
def _embed_cached(text: str) -> tuple[float, ...] | None:
    vec = _encode(text)
    # Cache immutable tuples so a caller can't mutate the shared entry.
    return tuple(vec) if vec is not None else None


def embed(text: str, *, cache: bool = False) -> list[float] | None:
    """Embed text into a float vector, or None if embeddings are unavailable.

    Pass cache=True for text that repeats across turns (a task description is
    identical every turn; a running summary changes only every few turns) to
    reuse the vector instead of re-encoding. Leave it False for the unique
    per-turn user query."""
    if not text or not text.strip():
        return None
    if cache:
        cached = _embed_cached(text)
        return list(cached) if cached is not None else None
    return _encode(text)


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors (0.0 on any issue)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))
