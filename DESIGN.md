# Design: Task-Scored AI Interaction Platform

Design spec for adding the `prompt.md` feature set to the existing FastAPI +
Postgres + React app. Scope: all 7 sections. Deliverable posture:
**production integration first**, with lightweight benchmark scripts kept
alongside (not blocking) the rollout.

This document is design-only. Implementation follows via `/sc:implement`.

---

## 0. What already exists (baseline)

| Layer | Today |
|---|---|
| Backend | FastAPI, async SQLAlchemy, Postgres; cookie auth (`get_current_user`) |
| Sessions | `ChatSession` per user, `messages` = JSON list of `{role, content}` |
| Chat LLM | **Nemotron** (NVIDIA OpenAI-compatible), key per-request via `X-Nemotron-Key`, full history sent each turn (`app/services/nemotron.py`) |
| Gemini | `app/services/gemini.py` — currently only `generate_feedback_question(messages)` |
| Feedback loop | After each turn, a background task generates a feedback question, stores it (`feedback_question_store`, blocks next turn via 409), and pushes it over `feedback_connection_manager`. `feedback_entry.chat_context` snapshots the conversation. |
| Frontend | React: `ChatView.jsx`, `FeedbackPanel.jsx` (modal) |

**Key insight that shapes everything below:** the post-turn background task and
its WebSocket push channel already exist. Scoring and summary maintenance reuse
that channel — but the Gemini call is **de-coupled from per-turn cadence**: it
now fires **once every 3–4 turns** (a batch of 3–4 user messages + 3–4 LLM
replies), and feedback is **no longer asked after every message.**

---

## 1. System overview

```
                         POST /chat (user turn)
  React ChatView ───────────────────────────────────► FastAPI chat router
        ▲   ▲                                              │
        │   │                                              ▼
        │   │                                   ┌────────────────────────┐
        │   │   relevance_warning (Yes/No)      │  RelevanceGuardrail    │  ── in-process
        │   └───────────────────────────────────│  (embeddings, cosine)  │     embedding model
        │                                        └────────────────────────┘
        │                                              │ (passes)
        │                                              ▼
        │                                        Nemotron chat  ──► reply persisted
        │                                              │
        │   score + feedback pushed                    ▼  (background task, only every 3–4 turns)
        │◄─────────────────────────────────  ┌────────────────────────┐
   ScorePanel / FeedbackPanel                 │  Gemini: ONE batched    │
                                              │  call → {summary,scores,Q}│
                                              └────────────────────────┘
                                                       │ stores summary + score history

  POST /sessions/{id}/proof (multipart)  ──►  ProofSubmission (pending)  ──► Admin review queue
       (pre-submit anti-fraud warning)                                          │ verify/reject
                                                                                ▼
                                                                     Task-completion points awarded
```

Three new in-process services + one new domain (tasks/proof). No new deploy
target this round; the embedding model is chosen to *fit* AWS Lambda
free-tier limits so a later extraction to Lambda is a lift-and-shift, not a
rewrite.

---

## 2. Data model changes

New tables and columns (Alembic migration). Types shown Postgres-side.

### 2.1 `tasks` (new — admin-defined)
| column | type | notes |
|---|---|---|
| `id` | uuid pk | |
| `title` | text | |
| `description` | text | the "original task / theme" fed to guardrail + scorer |
| `difficulty` | enum(`easy`,`medium`,`hard`) | drives point weight |
| `base_points` | int | points for verified completion (pre-weight) |
| `proof_requirements` | jsonb | `{accepted_types: [image,url,file], instructions, min_items}` |
| `active` | bool | admin can retire tasks |
| `created_by` | uuid fk→users | admin |
| `created_at` | timestamptz | |

### 2.2 `chat_sessions` (extend)
| new column | type | notes |
|---|---|---|
| `task_id` | uuid fk→tasks | a session is started **against a task** |
| `context_summary` | text | rolling summary, updated by the combined Gemini call each turn |
| `summary_embedding` | jsonb/bytea (nullable) | cached embedding of the summary, refreshed when summary changes — avoids re-embedding it every guardrail check |
| `live_score` | float | latest LiveScore (0–100), denormalized for fast reads |
| `score_components` | jsonb | latest `{R,E,D,P}` |

### 2.3 `score_events` (new — history / benchmarking)
| column | type |
|---|---|
| `id` | uuid pk |
| `session_id` | uuid fk |
| `turn_index` | int |
| `responsiveness/elaboration/development/progress` | float (0–100) |
| `live_score` | float |
| `context_snapshot` | jsonb (the exact window sent to Gemini) |
| `created_at` | timestamptz |

Keeping `context_snapshot` per event is what lets us later benchmark
"is a 4–5 turn window enough?" against real traffic without re-running sessions.

### 2.4 `proof_submissions` (new)
| column | type | notes |
|---|---|---|
| `id` | uuid pk | |
| `session_id` / `task_id` / `user_id` | uuid fk | |
| `proof_type` | enum(`image`,`url`,`file`) | |
| `storage_ref` | text (nullable) | object-store/disk path for image/file |
| `url` | text (nullable) | for url proofs |
| `sha256` | text (nullable) | exact-dupe detection |
| `phash` | text (nullable) | perceptual hash (images) — stored now, used by reviewers + future auto-checks |
| `metadata` | jsonb | captured EXIF/C2PA/mime/size — stored now, mined later |
| `status` | enum(`pending`,`verified`,`rejected`) | default `pending` |
| `reviewer_id` | uuid fk (nullable) | human reviewer |
| `review_notes` | text (nullable) | |
| `quality_factor` | float (nullable) | reviewer-set 0–1, feeds completion points |
| `warning_ack_at` | timestamptz | when the user acknowledged the anti-fraud warning |
| `created_at` / `reviewed_at` | timestamptz | |

### 2.5 `point_awards` (new — ledger, anti-gaming)
| column | type | notes |
|---|---|---|
| `id` | uuid pk | |
| `user_id` / `task_id` / `proof_id` | uuid fk | |
| `points` | int | final awarded |
| `created_at` | timestamptz | |
| unique | `(user_id, task_id)` | **one completion award per user per task** |

---

## 3. Component designs

### 3.1 Section 1 — Embedding model (in-process, Lambda-sized)

**New:** `app/services/embeddings.py` — lazy singleton, model loaded once,
`embed(text) -> list[float]` run via `asyncio.to_thread` (mirrors the
nemotron off-loop pattern).

**Recommended default:** `bge-small-en-v1.5` (384-dim, ~130 MB) for the best
accuracy-per-MB, or `all-MiniLM-L6-v2` (384-dim, ~80 MB) if cold-start/memory
is tighter. Serve via **ONNX Runtime + int8 quantization** so the artifact and
RAM footprint stay inside Lambda free-tier limits (target < ~250 MB unzipped
incl. deps, sub-second warm inference).

**Candidate matrix to benchmark** (script `benchmarks/embeddings_bench.py`,
offline, does not block rollout):

| model | dim | ~size | what we measure |
|---|---|---|---|
| all-MiniLM-L6-v2 | 384 | 80MB | accuracy, P/R, FP/FN, latency, RAM, $/1k |
| bge-small-en-v1.5 | 384 | 130MB | ″ |
| gte-small | 384 | 120MB | ″ |
| e5-small-v2 | 384 | 130MB | ″ |

Selection objective (from prompt §1): **smallest model that clears the
relevance accuracy bar.** The script emits a table + picks the model; the
chosen id goes to `settings.embedding_model`.

### 3.2 Section 2 — Relevance guardrail

**New:** `app/services/relevance.py`.

Flow, injected into `POST /chat` **before** the Nemotron call:

1. `q = embed(body.message)`.
2. Compare against **two** anchors: the session `summary_embedding` (rolling
   context) and the `task.description` embedding. `score = max(cos(q, summary),
   cos(q, task))` — related to *either* the recent thread or the assigned task
   counts as relevant. Note the summary refreshes only every 3–4 turns (§3.4),
   so between batches the guardrail runs against a slightly stale summary; the
   `task` anchor covers drift, and this is acceptable since the guardrail only
   raises a soft, dismissible warning.
3. If `score < settings.relevance_threshold` **and** the request did not set
   `acknowledge_offtopic`, **short-circuit**: return `ChatResponse` with
   `relevance_warning = { score, message }` and **do not call Nemotron / do not
   persist anything.**
4. Frontend shows the warning modal (prompt §2 copy) with **Yes, continue** /
   **No, go back**. "Yes" re-POSTs the same message with
   `acknowledge_offtopic: true`, which bypasses the check.

**Threshold caveat (important):** cosine similarities for MiniLM/bge on
*related* text typically land **0.3–0.8**, and unrelated text **0.1–0.3**. A
`0.15` cut is almost certainly **too low** (it will basically never fire). The
`0.15` in the prompt is explicitly "to be benchmarked, not assumed." Ship it as
`settings.relevance_threshold` (default 0.15 to honor the spec) but treat
`benchmarks/threshold_bench.py` as a fast-follow that sweeps 0.1–0.6 on a
labelled on/off-topic set and reports P/R, false-warning rate, and detection
rate per task type to pick the real value.

### 3.3 Section 3 — Sliding-window context builder

**New:** `app/services/context_window.py` →
`build_scoring_context(session) -> dict`:

```
{ "task": task.description,
  "summary": session.context_summary,
  "recent_user":  last N user messages,      # N = settings.window_user_turns (default 5)
  "recent_llm":   last N assistant messages } # settings.window_llm_turns (default 5)
```

This window is the **input to the Gemini scoring/summary call** (§3.4), *not*
the Nemotron chat context. (Nemotron still receives its history as today;
windowing Nemotron too is a possible cost optimization, noted but out of scope.)

Window sizes are config so `benchmarks/window_bench.py` can later test 3/5/7
turns for scoring stability and information loss.

### 3.4 Section 4 — Scoring (ONE combined Gemini call, batched every 3–4 turns)

**Cadence:** the Gemini call is **not** per-turn. It fires once per **batch of
3–4 turns** (`settings.score_interval_turns`, default 4). A turn counter on the
session (or `len(messages) // 2 % interval == 0`) decides when the background
task actually calls Gemini; on non-boundary turns the task is a no-op. This
means: one Gemini call per ~4 turns, and **feedback is asked only on those
boundaries — never after every message.**

**Change:** `app/services/gemini.py`. Replace `generate_feedback_question` with
`score_and_summarize(context) -> ScoreResult`, using Gemini's **`responseSchema`
structured output** (shape enforced at the API boundary — see §8.2):

```json
{
  "updated_summary": "…",
  "scores": { "responsiveness": 0-100, "elaboration": 0-100,
              "development": 0-100, "progress": 0-100 },
  "feedback_question": "…"
}
```

One call returns **all three** things the system needs per batch: the refreshed
summary (used by the guardrail + window until the next batch), the four
sub-scores, and the feedback question — exactly as specified.

The window sent to Gemini is the **batch just completed**: the last 3–4 user
messages + last 3–4 LLM replies (`window_user_turns`/`window_llm_turns`, aligned
to the interval) plus task + prior summary.

`LiveScore` is computed **server-side** from the sub-scores for consistency:

```
LiveScore = 0.30·R + 0.25·E + 0.25·D + 0.20·P
```

**Where it runs:** rename the existing `_generate_and_store_feedback_question`
background task to `_score_and_feedback`. It already runs *after* the chat
response is returned, so no added chat latency. It now:
1. **checks the batch boundary** — if this turn isn't a multiple of
   `score_interval_turns`, return immediately (no Gemini call),
2. builds the window (§3.3),
3. calls `score_and_summarize`,
4. writes `context_summary` (+ recomputes `summary_embedding`), `live_score`,
   `score_components` on the session,
5. appends a `score_events` row,
6. stores the feedback question and **pushes both score and question** over
   `feedback_connection_manager`.

**Feedback gating:** the existing "pending feedback question blocks the next
turn (409)" rule now engages **only on batch boundaries** — since a question is
produced roughly every 4 turns, the user answers ~once per batch instead of
every message. Between batches, chatting is unblocked.

Frontend gains a **ScorePanel** subscribed to the same push channel.

### 3.5 Section 5 — Task-completion points

Completion points are **separate** from LiveScore and awarded **only** after a
proof is human-verified (§3.6):

```
award = round(task.base_points · difficulty_weight · quality_factor)
   difficulty_weight: easy 1.0 / medium 1.5 / hard 2.0   (config)
   quality_factor:    reviewer-set 0–1 at verification    (§3.6)
```

Interaction with LiveScore: kept as **distinct dimensions** — a session shows
`live_score` (conversation quality, continuous) and `completion_points`
(one-time, gated on proof). A "total" is a presentation concern, not a mixed
scalar, so gaming one can't inflate the other.

**Anti-gaming:** award written to `point_awards` with `unique(user_id, task_id)`
→ a task pays out **once** per user; verification gate + evidence dedupe (§3.6)
prevents claim-without-work.

### 3.6 Section 6 — Proof of completion (human-verified this round)

**New endpoints:**
- `POST /sessions/{id}/proof` (multipart) — accepts `image` / `file` upload or
  `url`, per the task's `proof_requirements.accepted_types`. Requires
  `warning_ack` (§3.7). On submit:
  - compute `sha256` (all) and `phash` (images); capture `metadata`
    (mime, size, EXIF/C2PA if present).
  - **exact-duplicate auto-reject:** if `sha256` already exists for this task
    (any user), reject immediately — cheap and worth doing even in human-only
    mode.
  - else insert `status = pending`.
- `GET /sessions/{id}/proof` — submission status for the user.

**Admin review (human-only for now):**
- `GET /admin/proofs?status=pending` — queue.
- `POST /admin/proofs/{id}/review` — `{decision: verified|rejected,
  quality_factor, notes}`. On `verified`, write the `point_awards` row (§3.5)
  inside the same transaction.

**Storage:** disk/object-store via `storage_ref` (S3-ready abstraction);
`settings` holds max size + allowed mime types.

Valid proof = matches the task's declared `accepted_types` and passes exact-dupe
+ (future) automated checks. Perceptual hash + metadata are **captured now** so
the deferred automated layer (§3.7) is a pure add-on, no re-collection.

### 3.7 Section 7 — Anti-fraud guardrail

**Pre-submission warning (built now):** a modal shown **before** the proof form,
stating the three required points verbatim in intent:
1. proof must be the participant's own actual work,
2. fabricated / manipulated / misleading / falsely-submitted evidence is
   prohibited,
3. faking completion → **disqualification + removal of points**.

User must tick an acknowledgment; the submit endpoint requires it and stores
`warning_ack_at`. Deterrent-first, not hostile.

**Enforcement primitives (built now):**
- exact-dupe rejection (`sha256`),
- disqualification path: admin flag on `users` (add `disqualified` bool) +
  cascade that voids `point_awards` for that user.

**Automated detection (designed, deferred per decision):** the schema already
stores `phash`, `metadata`, `sha256`, so a later round can add, without new
data collection:
- **reused evidence:** `phash` near-dupe across users/tasks,
- **edited/generated images:** EXIF/C2PA provenance checks, ELA, and an
  ML/heuristic edit-detector,
- **evidence-vs-task mismatch:** an LLM cross-check of the proof against
  `task.description`,
- **wrong-owner evidence:** reverse-image / origin checks.
These are documented as the fast-follow; only the human queue ships this round.

### 3.8 Leaderboard (modal)

Users can open a **leaderboard modal** ranking participants by verified
achievement.

**Ranking source:** the `point_awards` ledger (§2.5) is the source of truth —
i.e. **only verified task-completion points count**, so the board can't be
gamed by chat activity alone. Ordering:

```
rank by  SUM(point_awards.points) DESC        -- total verified points
tie-break  COUNT(DISTINCT task_id) DESC,       -- more tasks completed
           MIN(created_at) ASC                 -- earned earlier wins ties
```

Optionally surface each user's rolling `AVG(live_score)` as a secondary,
non-ranking column (conversation quality), clearly separated from the points
that determine rank.

**Backend — new endpoint:**
`GET /leaderboard?limit=50` → `[{rank, display_name, total_points,
tasks_completed, avg_live_score}]`, plus a `me` object with the caller's own
rank even if outside the top N (so a user always sees where they stand). One
aggregate query over `point_awards` joined to `users`; cache for ~30–60s since
it changes only on verification.

**Privacy:** expose a `display_name`/handle, never email. Disqualified users
(§3.7) are excluded from the board.

**Frontend — new `LeaderboardModal.jsx`:** an MUI `Dialog` (see §6) with a
`Table` body. Opened from a header/sidebar "Leaderboard" button; fetches on open
via `api.getLeaderboard()`; renders a ranked list with the caller's own row
highlighted (`Chip` for rank), and is **non-blocking** (X / backdrop-click to
close) — unlike the feedback modal.

---

## 4. API surface (summary)

| method | path | purpose | auth |
|---|---|---|---|
| POST | `/tasks` | create task | admin |
| GET | `/tasks` / `/tasks/{id}` | list / detail | user |
| POST | `/session` | **now takes `task_id`** | user |
| POST | `/chat` | **+ relevance pre-check; `acknowledge_offtopic` flag; response may carry `relevance_warning`** | user |
| GET | `/sessions/{id}/score` | latest score + components | user |
| POST | `/sessions/{id}/proof` | submit proof (multipart, requires `warning_ack`) | user |
| GET | `/sessions/{id}/proof` | proof status | user |
| GET | `/leaderboard` | ranked users by verified points (+ caller's own rank) | user |
| GET | `/admin/proofs` | review queue | admin |
| POST | `/admin/proofs/{id}/review` | verify/reject + quality_factor | admin |

Score + feedback continue to arrive over the **existing** `feedback_connection_manager` push channel (no polling added).

---

## 5. Config additions (`app/config.py`)

```
embedding_model            = "BAAI/bge-small-en-v1.5"
relevance_threshold        = 0.15        # benchmark before trusting
score_interval_turns       = 4           # Gemini scoring/feedback fires every 3–4 turns
window_user_turns          = 4           # aligned to the batch
window_llm_turns           = 4
difficulty_weights         = {easy:1.0, medium:1.5, hard:2.0}
proof_storage_backend      = "disk"|"s3"
proof_max_bytes            = 10_000_000
proof_allowed_mime         = [...]
```

---

## 6. Frontend changes

**UI library: Material UI (MUI v6, `@mui/material` + `@emotion`).** All *new*
components are built with MUI primitives — `Dialog` for modals, `Table`/`Chip`
for the leaderboard and score breakdown, `LinearProgress` for the live score,
`Rating`/`ToggleButton` for admin review, `Snackbar` for warnings. This is a
stack addition: the existing components (`ChatView`, `FeedbackPanel`,
`ApiKeyModal`) are hand-rolled with `App.css` classes like `.modal-overlay`.

**Adoption strategy (avoid a half-migrated UI):** wrap the app in a single MUI
`ThemeProvider` + `CssBaseline` and map the current palette/spacing into the
theme so old and new components stay visually consistent. New work uses MUI
`Dialog` (not the hand-rolled `.modal-overlay`); existing modals can be
ported opportunistically but that's not a blocker for this round. Call this out
as a decision because it affects bundle size and every new component below.

- **New-chat flow:** task picker (MUI `Autocomplete`/`Select` over `active` tasks) → `POST /session` with `task_id`.
- **Relevance modal:** MUI `Dialog` on `relevance_warning` showing prompt §2 copy; "Yes, continue" re-POSTs with `acknowledge_offtopic`, "No, go back" restores the draft.
- **ScorePanel:** live `LiveScore` (MUI `LinearProgress`/gauge) + R/E/D/P breakdown, updates from the push channel (alongside `FeedbackPanel`).
- **Proof submission:** anti-fraud warning `Dialog` + acknowledgment `Checkbox` → upload/url form → status view.
- **LeaderboardModal:** non-blocking MUI `Dialog` (closable), opened from header/sidebar, `Table` ranked list with the caller's row highlighted.
- **Admin review UI:** queue + verify/reject (MUI `DataGrid`); thin internal page, flag if out of scope for round 1.

---

## 7. Rollout sequencing

1. **Migration + Task entity** (§2.1–2.2) and task-picker; sessions bind to a task.
2. **Embeddings service + guardrail** (§3.1–3.2) with default threshold; relevance modal.
3. **Combined Gemini call** (§3.4) — refactor the existing background task to fire only on the 3–4-turn boundary and return summary + scores + question; ScorePanel.
4. **Proof + human review + anti-fraud warning** (§3.6–3.7) and points ledger (§3.5).
5. **Benchmark scripts** (`benchmarks/`) run in parallel, feeding back the final embedding model, threshold, and window size.

---

## 8. Open risks / call-outs (discussion)

### 8.1 The 0.15 relevance threshold is very likely wrong
**Risk.** `bge-small`/`MiniLM` cosine similarities for *related* text usually sit
**0.3–0.8** and for *unrelated* text **0.1–0.3**. A `< 0.15` cutoff will fire
almost never — the guardrail would be effectively off, and prompt §2's whole
point (catching off-topic drift) is lost. The number in the prompt is a
placeholder the author explicitly flagged for benchmarking.
**Why it's subtle.** The "right" threshold is model-specific *and*
normalization-specific: raw cosine vs. the model's typical similarity floor
differ, and some models (e5/bge) expect a `"query:"`/`"passage:"` prefix that
shifts the whole distribution. Ship the wrong prefix convention and every score
moves.
**Decision (settled): ship 0.15 for now.** A single global
`relevance_threshold=0.15` is used in this round — provisional and un-trusted,
but good enough to wire the guardrail end-to-end. `benchmarks/threshold_bench.py`
(sweep 0.1→0.6 on a labelled on/off-topic set, reporting false-warning rate and
detection rate per task type) is a **fast-follow that will replace the value**,
and may later justify per-task-type thresholds — but that's deferred, not
built now. Because the warning is soft (§8.4), a mis-tuned 0.15 costs at most an
occasional dismissible prompt, so shipping it is low-risk.

### 8.2 One Gemini call, three responsibilities → parsing/degradation
**Risk.** The batched call returns `{updated_summary, scores{4}, feedback_question}`.
If Gemini returns malformed JSON, a missing field, or an out-of-range score, a
naive parse could crash the background task — or worse, write a garbage summary
that then poisons the next guardrail check *and* the next scoring window.
**Decision (settled): use Gemini `responseSchema`.**
- Gemini's **structured-output `responseSchema`** mode enforces the
  `{updated_summary, scores{4}, feedback_question}` shape at the API boundary, so
  we never parse free-form text or regex JSON out of prose.
- Validate server-side with a Pydantic model (scores clamped to 0–100); on any
  validation failure, **degrade gracefully**: keep the *previous* summary and
  score, skip this batch, log it, and let the next boundary retry. The chat
  itself is never blocked — scoring is best-effort background work.
- Guard the **summary specifically**: only overwrite `context_summary` +
  `summary_embedding` when the new summary passes validation *and* is non-empty,
  because a bad summary has downstream blast radius (§3.2, §3.3).
- Consider a cheap sanity check that the returned summary isn't wildly shorter
  than the prior one (truncation guard).

### 8.3 Guardrail latency on the critical path
**Risk.** Unlike scoring, the guardrail runs **synchronously before Nemotron** on
every turn. A cold model load (first request) or per-request re-embedding of the
summary would add visible latency to the chat.
**Decision / mitigation.**
- Preload the embedding model as a **process-lifetime singleton at startup**
  (FastAPI lifespan), so no request pays the load cost.
- **Cache the anchor embeddings:** `summary_embedding` is stored on the session
  and only recomputed when the summary changes (every 3–4 turns); the task
  embedding is computed once per task. So each turn's check is **one `embed()` of
  the new query + two dot-products** — sub-10ms on CPU for a 384-dim model.
- ONNX + int8 keeps even the query-embed fast and Lambda-portable later.

### 8.4 Stale summary between batches
**Risk.** Because the summary refreshes only every 3–4 turns (§3.4), the guardrail
and scoring window operate on a summary that can be up to ~3 turns behind. A fast
topic pivot mid-batch could be judged against outdated context.
**Why it's acceptable.** Two cushions: (1) the guardrail also anchors on the
**stable task description**, which doesn't drift, so genuine on-task turns still
pass; (2) the guardrail's only consequence is a **soft, dismissible warning**,
not a hard block — a false warning costs one click, not a lost message. The
batching trade (fewer Gemini calls) is worth this bounded staleness. **Open
question for you:** if mid-batch drift turns out to matter, we can cheaply
refresh *only* the summary embedding against the latest user turn without a full
Gemini call — worth prototyping if benchmarks show it.

### 8.5 Material UI is a stack addition (new §6)
**Risk.** Introducing MUI alongside hand-rolled `App.css` components risks a
half-migrated, visually inconsistent UI and a bundle-size bump.
**Decision / mitigation.** Single `ThemeProvider` + `CssBaseline` mapping the
current palette into the MUI theme; all *new* components are MUI, existing ones
ported opportunistically (not a blocker). Tree-shake imports (`@mui/material/Button`
paths) to contain bundle growth.

### 8.6 Nemotron still receives full history
**Risk.** The sliding window is for the Gemini scorer; Nemotron chat still gets
the full message list, so long sessions grow token cost/latency there.
**Decision.** Out of scope for this round — but the same window builder (§3.3)
could cap Nemotron's context later. Flagged so it's a conscious choice, not an
oversight.
