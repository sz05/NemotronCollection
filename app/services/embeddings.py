"""Sentence embedding helpers for semantic relevance + scoring.

Backed by fastembed (ONNX Runtime) rather than sentence-transformers/torch:
same `all-MiniLM-L6-v2` weights and vectors, but ~200MB resident instead of
~1GB and a ~1-2s cold start instead of several seconds -- no torch in the
image. The heavy dep is imported lazily inside `_get_model` so importing this
module never fails when it's absent; the model is loaded once and cached in a
module-level singleton, and any load failure yields None so callers fail open.

fastembed L2-normalizes its output; sentence-transformers here did not
(`normalize_embeddings=False`). This does not change any downstream score:
`cosine()` self-normalizes, so cosine(a, b) is identical for normalized and
un-normalized vectors. `relevance_threshold` is therefore unaffected.
"""

import math
from functools import lru_cache

from app.config import settings

# Singleton model + a flag so we only attempt (and log) the load once.
_model = None
_load_failed = False


def _get_model():
    """Lazily load and cache the fastembed TextEmbedding, or None if unavailable."""
    global _model, _load_failed
    if _model is not None:
        return _model
    if _load_failed:
        return None
    try:
        from fastembed import TextEmbedding

        _model = TextEmbedding(model_name=settings.embedding_model)
        return _model
    except Exception:
        # Missing dep, no network for the one-time model download, etc.
        _load_failed = True
        return None


def _embed_one(model, text: str):
    """Run one text through fastembed, returning its numpy vector.

    `.embed()` takes an iterable and returns a generator of ndarrays; we pull
    the single result out.
    """
    return next(iter(model.embed([text])))


def warmup() -> bool:
    """Force the (otherwise lazy) model load + one tiny encode so the FIRST
    real /chat request doesn't pay the multi-second cold start. Safe to call
    from app startup; returns True once the model is ready."""
    model = _get_model()
    if model is None:
        return False
    try:
        _embed_one(model, "warmup")
        return True
    except Exception:
        return False


def _encode(text: str) -> list[float] | None:
    model = _get_model()
    if model is None:
        return None
    try:
        vec = _embed_one(model, text)
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
