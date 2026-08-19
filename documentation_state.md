# Implementation State — Task-Scored AI Platform

What was built on top of the existing Nemotron chat harness to deliver the
feature set in `prompt.md` / `DESIGN.md`: an admin-defined **task** system, an
embedding **relevance guardrail**, a compact **sliding-window context**, batched
**live scoring + feedback** via Gemini, **proof-of-completion** with human
review, an anti-fraud warning, and a **leaderboard** — plus a Material-UI
frontend for all of it.

This document describes the *as-built* system (files, data flow, how each piece
works). `DESIGN.md` holds the rationale and the decisions behind it.

---

## 1. Baseline it was built on

- **Backend:** FastAPI, async SQLAlchemy/SQLModel, Postgres. Auth via httpOnly
  cookie (`get_current_user`). Sessions store `messages` as a JSONB list of
  `{role, content}`.
- **Chat LLM:** Nemotron (NVIDIA), key supplied per-request (`X-Nemotron-Key`),
  in `app/services/nemotron.py`. Unchanged.
- **Gemini:** `app/services/gemini.py`, previously only a per-turn feedback
  question. Now also does batched scoring.
- **Schema management:** SQLModel `create_all` on startup — **no Alembic**. New
  *tables* are created automatically; new *columns on existing tables* need an
  explicit migration (see §8).

---

## 2. Data model additions (`app/models.py`)

Four new tables + columns on two existing tables.

**New tables**
| table | purpose | key fields |
|---|---|---|
| `task` | admin-defined task a chat is scored against | `title, description, difficulty, base_points, proof_types (jsonb), instructions, active, created_by` |
| `score_event` | one row per scoring batch (history/analytics) | `session_id, turn_index, responsiveness, elaboration, development, progress, live_score, context_snapshot (jsonb)` |
| `proof_submission` | evidence of task completion | `session_id, task_id, user_id, proof_type, storage_ref, url, sha256, phash, meta (jsonb), status, reviewer_id, review_notes, quality_factor, warning_ack_at, reviewed_at` |
| `point_award` | ledger of awarded completion points | `user_id, task_id, proof_id, points`; **`UNIQUE(user_id, task_id)`** |

**New columns**
- `chat_session`: `task_id` (FK→task, nullable), `context_summary` (TEXT),
  `live_score` (float), `score_components` (jsonb).
- `app_user`: `display_name` (TEXT), `disqualified` (bool).

> Note: `meta` is used instead of `metadata` because `metadata` is reserved on
> SQLModel/SQLAlchemy declarative classes.

Repository helpers for all of these live in `app/repository.py`
(`create_task`, `list_tasks`, `get_task`, `add_score_event`,
`update_session_score`, `create_proof`, `find_proof_by_sha`,
`list_pending_proofs`, `review_proof`, `award_points`, `leaderboard`, and an
updated `create_session(..., task_id=None)`).

---

## 3. Semantic matching / relevance guardrail

Three new in-process services.

### 3.1 Embeddings — `app/services/embeddings.py`
- `embed(text) -> list[float] | None`, `cosine(a, b) -> float`.
- Lazily loads a **SentenceTransformer singleton** (`all-MiniLM-L6-v2`, 384-dim)
  on first use; heavy imports (`sentence_transformers`/`torch`) are **inside the
  function**, so importing the module never fails when the deps are absent.
- **Fail-open:** any load/encode error returns `None`, and callers treat that as
  "relevant" — a missing optional dependency can never block a user.

### 3.2 Relevance — `app/services/relevance.py`
- `evaluate(query, summary, task_description) -> RelevanceResult(relevant, score)`.
- `score = max(cosine(query, summary), cosine(query, task_description))` — a
  query on-topic for *either* the running summary or the assigned task passes.
- `relevant = score >= settings.relevance_threshold` (default **0.15**).
- If embeddings are unavailable, returns `relevant=True, score=1.0`.

### 3.3 Where it runs — `app/routers/chat.py` (`/chat`)
Before Nemotron is called:
```python
if session.task_id and not body.acknowledge_offtopic:
    task = await get_task(db, session.task_id)
    result = await asyncio.to_thread(          # CPU-bound embed off the event loop
        evaluate, body.message, session.context_summary or "", task.description
    )
    if not result.relevant:
        return ChatResponse(session_id=..., reply="",
            relevance_warning={"score": result.score, "message": _OFFTOPIC_MESSAGE})
```
On an off-topic turn the handler **returns immediately** — Nemotron is not
called and **nothing is persisted**. The frontend shows a soft warning; "Yes,
continue" re-POSTs the same message with `acknowledge_offtopic=true`, which skips
the check.

---

## 4. Sliding-window context — `app/services/context_window.py`

`build_scoring_context(task_description, summary, messages) -> dict`:
```
{ task, summary, recent_user: last window_user_turns, recent_llm: last window_llm_turns }
```
This bounded payload is what the **Gemini scorer** receives — *not* the Nemotron
chat context (Nemotron still gets full history). Window sizes are config
(`window_user_turns`, `window_llm_turns`, default 4 each).

---

## 5. Live scoring + feedback (batched)

### 5.1 Gemini — `app/services/gemini.py`
- Original `generate_feedback_question` kept intact.
- New `score_and_summarize(context) -> dict` returns
  `{updated_summary, scores{responsiveness,elaboration,development,progress}, feedback_question}`
  in **one call**, from the sliding-window context. Scores are clamped 0–100;
  malformed responses raise `GeminiError`.

### 5.2 Orchestration — `app/services/scoring.py`
`score_and_feedback(session_id, task_description, messages)` runs as a
**background task** after each `/chat` reply:
1. `turn_index = len(messages)//2`. **Fires only on the boundary**:
   `turn_index % settings.score_interval_turns == 0` (default every 4 turns).
   Otherwise it's a no-op → no Gemini call, no feedback every message.
2. Reads the prior `context_summary`, builds the window, calls
   `score_and_summarize`.
3. `LiveScore = 0.30R + 0.25E + 0.25D + 0.20P` (computed server-side).
4. Persists: `update_session_score` (overwrites `context_summary`, `live_score`,
   `score_components` — summary only if non-empty) and `add_score_event`
   (history row with the four sub-scores + the message-window snapshot).
5. Stores the feedback question (`feedback_question_store`) and pushes both over
   the existing `feedback_connection_manager` WebSocket.
- **Fully guarded:** any `GeminiError`/exception is logged and swallowed, keeping
  the prior summary/score — a scoring failure never crashes the turn.

### 5.3 Score read endpoint — `app/routers/chat.py`
`GET /sessions/{id}/score → {session_id, live_score, components}` — latest score
for the ScorePanel.

> The running summary is saved only as the **latest** value on
> `chat_session.context_summary` (overwritten each batch); it is not versioned
> and not exposed by any API.

---

## 6. Task completion, proof & anti-fraud

### 6.1 Tasks — `app/routers/tasks.py`
`POST /tasks` (create), `GET /tasks` (active list), `GET /tasks/{id}`. A chat is
started against a task via `POST /session {task_id}`.

### 6.2 Proof submission — `app/routers/proof.py`
- `POST /sessions/{id}/proof` (multipart): `proof_type` ∈ {image, url, file},
  an uploaded file **or** a URL, and a required `warning_ack`.
  - Requires acknowledgment (else 400).
  - Computes `sha256` of file bytes; `phash` for images (lazy `PIL`/`imagehash`,
    tolerates absence → `None`); captures `meta`.
  - **Exact-duplicate auto-reject** via `find_proof_by_sha` (409) even in the
    human-only flow.
  - Stores the row `status="pending"` and the file under
    `settings.proof_upload_dir`.
- `GET /sessions/{id}/proof` — submission status.

### 6.3 Human review — `app/routers/admin.py`
- `GET /admin/proofs` — pending queue.
- `POST /admin/proofs/{id}/review {decision, quality_factor, notes}`. On
  `verified`, in the same commit it writes a `point_award`:
  `points = round(base_points * difficulty_weight * quality_factor)`.
  `UNIQUE(user_id, task_id)` guarantees **one payout per task per user**.

### 6.4 Anti-fraud
- Pre-submission warning + acknowledgment (`ProofModal`, stored as
  `warning_ack_at`).
- `sha256` exact-dupe rejection; `disqualified` flag on users.
- Automated forensics (phash reuse, EXIF/C2PA, LLM cross-check) is **designed but
  deferred** — the schema already stores `phash`/`meta`/`sha256` so it's a later
  add-on with no re-collection.

---

## 7. Leaderboard — `app/routers/leaderboard.py`

`GET /leaderboard?limit=50 → {entries[], me}`. Ranked from the **`point_award`
ledger only** (verified points — can't be gamed by chat activity):
`SUM(points) DESC, COUNT(DISTINCT task_id) DESC, MIN(created_at) ASC`. The `me`
object always includes the caller's own rank even if outside the top N.

---

## 8. Frontend (Material UI)

- **Stack:** added `@mui/material` + `@emotion` + `@mui/icons-material`.
  `main.jsx` wraps the app in `ThemeProvider` (+ `theme.js`). Existing plain-CSS
  components still work; new components are MUI.
- **New components** (`frontend/src/components/`):
  - `TaskPicker.jsx` — Dialog to pick a task on new chat → `createSession(taskId)`.
  - `RelevanceWarningModal.jsx` — "This looks off-topic" Dialog wired into
    `ChatView`'s send flow (Yes = resend with ack; No = restore draft).
  - `ScorePanel.jsx` — live score + R/E/D/P, polls `getScore` on session change
    and after each send.
  - `LeaderboardModal.jsx` — non-blocking Dialog + Table, caller row highlighted.
  - `ProofModal.jsx` — anti-fraud warning + acknowledgment + upload/URL form.
- **API client** (`api/client.js`): `getTasks`, `createSession(taskId)`,
  `getScore`, `getLeaderboard`, `submitProof`, `getProofStatus`, and an
  `acknowledgeOfftopic` option on `sendChatMessage`.

---

## 9. Config additions (`app/config.py`)

```
embedding_model      = "sentence-transformers/all-MiniLM-L6-v2"
relevance_threshold  = 0.15          # provisional — benchmark before trusting
score_interval_turns = 4             # scoring/feedback every N turns
window_user_turns    = 4
window_llm_turns     = 4
difficulty_weights   = {"easy":1.0,"medium":1.5,"hard":2.0}
proof_upload_dir     = "uploads"
proof_max_bytes      = 10_000_000
```
(`cookie_samesite` was restored during integration — it had been dropped by a
config rewrite and is required by the auth cookie.)

---

## 10. Scripts

- `scripts/migrate_add_scoring_columns.py` — **idempotent** `ADD COLUMN IF NOT
  EXISTS` for the new `chat_session`/`app_user` columns (create_all handles the
  new tables). **Run this on any existing DB** or the new columns won't exist.
- `scripts/seed_task.py` — seeds a demo "Build a FastAPI to-do API" task
  (idempotent).
- `scripts/smoke_guardrail.py` — loads the real embedding model and prints
  relevance scores for on/off-topic samples.

---

## 11. How to run locally

```bash
# one-time: new columns on an existing DB
PYTHONPATH=. python scripts/migrate_add_scoring_columns.py
PYTHONPATH=. python scripts/seed_task.py

# embedding stack (CPU-only torch — avoids multi-GB CUDA wheels)
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install sentence-transformers

# backend + frontend
uvicorn main:app --host 127.0.0.1 --port 8000
cd frontend && npm install && npm run dev
```
Open **`http://localhost:5173`** (not `127.0.0.1` — CORS `allow_origins` only
lists the `localhost` form). For login without Google OAuth, set `DEV_AUTH=true`
in `.env`.

---

## 12. Verification status

- **Backend:** `compileall` clean, `import main` OK, full OpenAPI surface present.
- **Tests:** `pytest` → **12 passed** (two feedback tests updated for the batched
  architecture; a FK-order fix for the new `score_event` cleanup).
- **Embedding smoke test:** MiniLM loads; on-topic 0.38–0.57, off-topic
  0.00–0.03. The **borderline case ("JWT vs session cookies" for a login task)
  scored 0.125 — a false warning under the 0.15 threshold**, confirming the
  threshold needs benchmarking (DESIGN §8.1).
- **Frontend:** `npm run build` passes.
- **Browser E2E (Playwright + Chrome):** dev-login → save key → new chat against
  the seeded task → off-topic "banana bread" message → **the relevance warning
  modal appeared** ("This looks off-topic", score 0.03), before Nemotron was
  called. Verified visually.

---

## 13. Known limitations / follow-ups

1. **0.15 threshold is provisional** — build `benchmarks/threshold_bench.py` to
   pick a real value (the smoke test suggests ~0.05–0.10). MiniLM cosines are
   un-normalized; consider normalizing / the `query:`/`passage:` prefix convention.
2. **No schema migrations tool** — new columns needed a manual script. Consider
   adopting Alembic before production.
3. **Summary not historized** — only the latest `context_summary` is kept; not
   exposed via API. Could add it to `ScoreOut`/session detail and/or store per
   `score_event`.
4. **Automated proof forensics deferred** — only human review + sha256 dedupe
   ship now.
5. **Nemotron still gets full history** — the sliding window is scorer-only.
6. **Deploy note:** `sentence-transformers` pulls CUDA torch by default; install
   CPU torch explicitly, and bake the MiniLM model into the image (first run
   downloads ~90MB from HF).
7. **CORS host consistency** — align `frontend_origins` with whatever host the
   SPA is actually served from (`localhost` vs `127.0.0.1`).
```
