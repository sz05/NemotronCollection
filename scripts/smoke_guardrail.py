"""Smoke test for the relevance guardrail with the real embedding model.

Confirms (1) the embedding stack actually loads (embed != None), (2) cosine
similarity separates on-topic from off-topic queries, and (3) how the default
0.15 threshold behaves on realistic pairs.
"""

from app.config import settings
from app.services.embeddings import embed
from app.services.relevance import evaluate

TASK = (
    "Build a REST API in Python with FastAPI that lets users register, log in, "
    "and manage a personal to-do list stored in a Postgres database."
)
SUMMARY = "The user is setting up FastAPI routes and SQLAlchemy models for the to-do API."

CASES = [
    ("on-topic / task", "How do I hash passwords before storing them in Postgres?"),
    ("on-topic / continuation", "What's the best way to structure the SQLAlchemy models for tasks?"),
    ("borderline", "Should I use JWT or session cookies for the login flow?"),
    ("off-topic / mild", "What's a good recipe for banana bread?"),
    ("off-topic / hard", "Who won the 2018 FIFA World Cup final?"),
]


def main() -> None:
    v = embed("hello world")
    if v is None:
        print("FAIL: embed() returned None -- embedding stack not available")
        raise SystemExit(1)
    print(f"embedding model OK: {settings.embedding_model}  dim={len(v)}")
    print(f"threshold = {settings.relevance_threshold}\n")
    print(f"{'case':<26} {'score':>7}  relevant  would-warn?")
    print("-" * 60)
    for label, query in CASES:
        r = evaluate(query, SUMMARY, TASK)
        warn = "WARN" if not r.relevant else "-"
        print(f"{label:<26} {r.score:>7.3f}  {str(r.relevant):<8}  {warn}")


if __name__ == "__main__":
    main()
