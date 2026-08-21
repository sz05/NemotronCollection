"""A/B check: sentence-transformers vs fastembed for the relevance path.

Confirms the ONNX (fastembed) swap doesn't move the cosine scores that
`relevance_threshold` gates on. Run this while BOTH libs are still installed
(the pre-swap venv), before dropping sentence-transformers:

    python scripts/compare_embeddings.py

For each (query-clause, anchor) pair it prints the old vs new cosine and the
absolute delta. Because both backends use the same all-MiniLM-L6-v2 weights and
cosine self-normalizes, deltas should be ~1e-6. Exits non-zero if any pair
crosses the threshold differently, i.e. if the swap would flip a relevant/
off-topic verdict.
"""

import sys

from app.config import settings
from app.services.embeddings import cosine

# Representative anchors (task/summary) and queries (on- and off-topic) — the
# same kind of text the live relevance check compares.
ANCHORS = [
    "Build a BookMyShow clone with seat selection and payments using FastAPI.",
    "The user is implementing a movie ticket booking backend and its database schema.",
]
QUERIES = [
    "make a bookmyshow clone",          # on-topic
    "using fastapi and postgres",       # on-topic directive
    "give the file structure first",    # boilerplate directive
    "what's the weather in Paris today",  # clearly off-topic
    "how do I bake sourdough bread",    # clearly off-topic
]


def _st_encode(text: str) -> list[float]:
    from sentence_transformers import SentenceTransformer

    global _st
    try:
        _st
    except NameError:
        _st = SentenceTransformer(settings.embedding_model)
    vec = _st.encode(text, convert_to_numpy=True, normalize_embeddings=False)
    return [float(x) for x in vec.tolist()]


def _fe_encode(text: str) -> list[float]:
    from fastembed import TextEmbedding

    global _fe
    try:
        _fe
    except NameError:
        _fe = TextEmbedding(model_name=settings.embedding_model)
    vec = next(iter(_fe.embed([text])))
    return [float(x) for x in vec.tolist()]


def main() -> int:
    thr = settings.relevance_threshold
    max_delta = 0.0
    verdict_flips = 0

    print(f"threshold = {thr}\n")
    print(f"{'old':>8} {'new':>8} {'delta':>10}  verdict  pair")
    print("-" * 72)

    for a in ANCHORS:
        av_old, av_new = _st_encode(a), _fe_encode(a)
        for q in QUERIES:
            qv_old, qv_new = _st_encode(q), _fe_encode(q)
            old = cosine(qv_old, av_old)
            new = cosine(qv_new, av_new)
            delta = abs(old - new)
            max_delta = max(max_delta, delta)
            flipped = (old >= thr) != (new >= thr)
            verdict_flips += flipped
            mark = "FLIP!" if flipped else "ok"
            print(
                f"{old:8.4f} {new:8.4f} {delta:10.2e}  {mark:7}  "
                f"[{q[:28]}] x [{a[:24]}]"
            )

    print("-" * 72)
    print(f"max |delta| = {max_delta:.2e}   verdict flips = {verdict_flips}")
    if verdict_flips:
        print("FAIL: swap changes at least one relevant/off-topic verdict.")
        return 1
    print("PASS: fastembed matches sentence-transformers on every pair.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
