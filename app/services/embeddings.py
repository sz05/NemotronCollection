"""Sentence embedding helpers for semantic relevance + scoring.

Heavy deps (sentence_transformers/torch) are imported lazily inside functions
so importing this module never fails when they are absent. The model is loaded
once and cached in a module-level singleton; any load failure yields None so
callers can fail open.
"""

import math

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


def embed(text: str) -> list[float] | None:
    """Embed text into a float vector, or None if embeddings are unavailable."""
    if not text or not text.strip():
        return None
    model = _get_model()
    if model is None:
        return None
    try:
        vec = model.encode(text, convert_to_numpy=True, normalize_embeddings=False)
        return [float(x) for x in vec.tolist()]
    except Exception:
        return None


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
