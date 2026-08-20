# Improving the Reliability of Semantic Matching

How to make the relevance guardrail more reliable, prioritized cheapest/highest-
leverage first. Grounded in the as-built system (`app/services/embeddings.py`,
`app/services/relevance.py`, `app/routers/chat.py`) and today's smoke-test
findings.

## The problem, concretely

The current guardrail (`relevance.evaluate`) embeds the user's message with
`all-MiniLM-L6-v2` and compares it against the running summary and the task
description:

```
score = max(cosine(query, summary), cosine(query, task_description))
relevant = score >= settings.relevance_threshold   # default 0.15
```

Today's `scripts/smoke_guardrail.py` run exposed the weakness:

| case | score | verdict |
|---|---|---|
| on-topic (task) | 0.384 | pass ✅ |
| on-topic (continuation) | 0.570 | pass ✅ |
| **borderline: "JWT vs session cookies?" for a login-API task** | **0.125** | **false WARN ❌** |
| off-topic (banana bread) | 0.027 | warn ✅ |
| off-topic (World Cup) | 0.000 | warn ✅ |

So it measures the right thing but is **mis-calibrated and under-sourced**: a
clearly on-topic query dipped below the 0.15 cut. MiniLM's raw cosines compress
related content into a narrow band, and a single short query against a single
anchor is high-variance.

---

## Tier 1 — fix the measurement (do first, low effort)

### 1. Benchmark the threshold instead of assuming 0.15
The single biggest win. Build a labeled set (~50–100 query/task pairs tagged
on/off-topic across a few task types), sweep `0.02 → 0.40`, and pick the value
that minimizes false-warns while still catching drift. The smoke numbers suggest
the real value is **~0.05–0.10**, not 0.15. Turns `relevance_threshold` from a
guess into a measured constant, and tells us whether a model swap (Tier 2) is
even worth it.

Deliverable: `benchmarks/threshold_bench.py` → table of precision/recall,
false-warning rate, and detection rate per threshold and per task type.

### 2. Two-band decision, not a single hard cut
The warning is already soft, so exploit that:
- `score ≥ high` → allow silently
- `low ≤ score < high` → **gray zone** (resolve via #6)
- `score < low` → warn

Almost all false-warnings live right at a single boundary; a band plus a
tie-breaker removes them. Config: `relevance_low`, `relevance_high`.

### 3. Normalize + use the model's intended prefixes
`embeddings.py` embeds with no prefix. Retrieval models (bge/e5) expect
`"query: …"` / `"passage: …"` framing — without it the whole similarity
distribution shifts and compresses (why 0.125 looks "low" for a related query).
Even on MiniLM, running query and task/summary through a consistent instruction
template tightens on/off-topic separation. Normalize embeddings so scores are
comparable across models.

---

## Tier 2 — improve the signal (medium effort)

### 4. Swap to a stronger small model — and benchmark the trade
`all-MiniLM-L6-v2` is a fine default but general-purpose. `bge-small-en-v1.5` or
`gte-small` (both 384-dim, Lambda-sized) separate on/off-topic noticeably better
with proper prefixes. Decide via `benchmarks/embeddings_bench.py` (DESIGN §3.1):
accuracy, P/R, FP/FN, latency, memory, cost.

### 5. Enrich the query and the anchors
`evaluate()` compares one short message against `max(summary, task)` — brittle.
- **Carry context into the query:** a follow-up like *"what about caching?"* is
  nearly contentless alone. Embed `last_user_turn + " " + new_message` so short
  pivots are judged in context.
- **More anchors, softer aggregate:** add the last few user turns (or a
  conversation centroid) alongside summary + task, and take a top-k mean instead
  of a single `max`. Reduces variance from any one noisy anchor.

### 6. LLM judge in the gray zone only
When cosine lands in the ambiguous band (#2), ask Gemini a one-token yes/no:
*"Is this message relevant to task X? y/n."* You pay an LLM call **only** on
borderline turns (rare), and it resolves exactly the cases embeddings are worst
at. Highest accuracy for near-zero average cost.

### 7. Smooth across turns (EMA), don't hard-cut per turn
Keep a rolling relevance score (exponential moving average) on the session and
warn on *sustained* drift, not a single dip. One tangential message shouldn't
nag; three in a row should. Naturally suppresses the single-low-but-legitimate
false positive.

---

## Tier 3 — robustness (higher effort, only if Tier 1–2 falls short)

### 8. Hybrid lexical + semantic
Add a keyword/BM25 overlap signal against the task's salient terms and combine
with cosine. Catches domain jargon embeddings miss, and vice-versa.

### 9. Per-task calibration (relative, not absolute)
At task creation, precompute an on-topic centroid from the description + a couple
of example on-topic queries, and score new queries as a **z-score against that
task's own distribution** rather than a global absolute cosine. Fixes the fact
that "0.15" means different things for different tasks.

### 10. Log every guardrail decision; monitor false-warn rate in prod
The `score_events` table already scaffolds this. Add a decisions log so the
threshold keeps getting tuned from real traffic instead of a one-off benchmark.

---

## Also worth fixing (correctness/ops, already visible in code)

- **Cache anchor embeddings.** The task embedding is recomputed every turn;
  compute it once per task, and recompute the summary embedding only when the
  summary changes (every ~4 turns). Consistency + latency.
- **Refresh the summary anchor mid-batch cheaply.** The summary refreshes only
  every `score_interval_turns`; between batches the guardrail runs on a stale
  summary (DESIGN §8.4). If drift matters, re-embed the summary against the
  latest turn without a full Gemini call.
- **Short/empty-text handling.** `embed()` returns `None` for empty text and the
  guardrail fails open; make sure very short queries (which embed poorly) route
  to the gray-zone path rather than a hard verdict.

---

## Recommended order

1. **#1 Benchmark the threshold** — stop guessing; also decides #4.
2. **#6 Gray-zone LLM fallback** + **#2 two-band** — together these fix the
   0.125 false-warn at near-zero runtime cost.
3. **#3 prefixes/normalize** + **#4 model swap** — slot into the same harness.
4. **#5 query/anchor enrichment**, then **#7 EMA smoothing**.
5. Tier 3 only if the false-warn rate is still too high after the above.

**Fastest path to "reliable":** #1 → #6 → #2. That's the minimum that would have
turned today's false-warn into a correct pass.
