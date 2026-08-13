# Implementation Workflow: Synthetic Data Collection Harness (V1)

Source: `context.md`
Strategy: systematic | Depth: normal

## Scope Guardrail (from context.md)

V1 = exactly these 5 components. Do NOT build OAuth, leaderboards, word-count limiters,
or scoring heuristics unless explicitly instructed later.

1. API Key Ingestion (Nemotron key, session-held)
2. Chat Harness (routes to Nemotron API)
3. Chat Persistence (DB save of prompts/responses)
4. Gemini Side-Panel (context-aware feedback questions)
5. Feedback Persistence (answers saved, linked to session)

Stack: FastAPI (Py 3.10+) backend API · PostgreSQL (asyncpg/SQLAlchemy or SQLModel) ·
httpx (async) · React (Vite) frontend SPA · Nemotron via user-supplied key · Gemini via
server-side `.env` key.

## Frontend Decision

Confirmed: **React (Vite) SPA**, calling the FastAPI backend as a pure JSON API (no
server-rendered templates). Backend must enable CORS for the Vite dev origin. This
supersedes the earlier Jinja2 assumption — Phase 0, 2, 3, and 4 below are updated
accordingly.

---

## Phase 0 — Project Scaffold

**Goal**: bootstrapable skeleton before any feature work.

| Task | Description | Depends on |
|---|---|---|
| 0.1 | Create `requirements.txt` (fastapi, uvicorn, sqlmodel or sqlalchemy+asyncpg, httpx, python-dotenv) | — |
| 0.2 | `main.py` app entrypoint + `uvicorn main:app --reload` boots | 0.1 |
| 0.3 | `.env.example` with `GEMINI_API_KEY`, `DATABASE_URL` (never a Nemotron key — that's per-session only) | 0.1 |
| 0.4 | `app/config.py` — settings loader (env vars via pydantic-settings or python-dotenv) | 0.3 |
| 0.5 | `app/db.py` — async engine/session setup (asyncpg) | 0.1 |
| 0.6 | Enable `CORSMiddleware` on the FastAPI app for the Vite dev origin (e.g. `http://localhost:5173`) | 0.2 |
| 0.7 | Scaffold `frontend/` with Vite + React (`npm create vite@latest frontend -- --template react`) | — |
| 0.8 | Frontend base: API client wrapper (fetch/axios) pointed at the FastAPI base URL, basic app shell/routing (chat view + side-panel layout) | 0.7 |

**Checkpoint 0**: `uvicorn main:app --reload` starts cleanly; DB connects; `/health` returns 200.
`npm run dev` in `frontend/` serves the React shell and it can reach `/health` through CORS.

---

## Phase 1 — Data Model & Persistence Layer

**Goal**: schema exists before any endpoint writes to it (unblocks Phase 3 & 5 in parallel later).

| Task | Description | Depends on |
|---|---|---|
| 1.1 | `ChatSession` model — id, created_at, (no Nemotron key stored) | 0.5 |
| 1.2 | `ChatMessage`/messages column — JSONB array `[{"role","content"}, ...]` on session (per context.md rule: keep it simple, one JSONB column, not a normalized messages table) | 1.1 |
| 1.3 | `FeedbackEntry` model — id, session_id (FK), question, answer, created_at | 1.1 |
| 1.4 | Alembic (or SQLModel `create_all`) migration/init script | 1.1, 1.2, 1.3 |
| 1.5 | Repository/service functions: `create_session`, `append_message`, `save_feedback` | 1.4 |

**Checkpoint 1**: migration applies cleanly to a fresh Postgres DB; unit test inserts a session + message row + feedback row.

---

## Phase 2 — API Key Ingestion + Chat Harness

**Goal**: components 1 & 2 from scope. These are coupled (key feeds the chat call) so build together.

| Task | Description | Depends on |
|---|---|---|
| 2.1 | React `ApiKeyModal` component — collects Nemotron key on session start, holds it in React state/context (not localStorage, to avoid persisting it) | 0.8 |
| 2.2 | Backend accepts the key **per-request only** (e.g. `X-Nemotron-Key` header sent with every `/chat` call from the React client) — never persisted to DB or logs, never stored server-side between requests | 2.1 |
| 2.3 | `app/services/nemotron.py` — async httpx client wrapping Nemotron chat completion call, key injected per-request from the header | 2.2 |
| 2.4 | `POST /chat` endpoint: reads key header, accepts user message + session id, calls Nemotron service, returns response | 2.3, 1.5 |
| 2.5 | React `ChatView` component: message list + input, calls `/chat` via the API client (attaching the key header from context), renders response | 2.1, 0.8 |
| 2.6 | Wire persistence: on each turn, append `{role:user}` and `{role:assistant}` to the session's JSONB messages via 1.5 | 2.4, 1.5 |

**Security checkpoint**: grep logs/DB writes in this phase to confirm the Nemotron key never appears in a log line or a persisted column.

**Checkpoint 2**: end-to-end manual test — enter key, send message, get Nemotron reply, reload DB row and confirm messages array grew.

---

## Phase 3 — Gemini Side-Panel (Async Feedback Generation)

**Goal**: component 4. Must be decoupled from the chat request path per context.md performance rule.

| Task | Description | Depends on |
|---|---|---|
| 3.1 | `app/services/gemini.py` — async client using server-side `GEMINI_API_KEY` from `.env` | 0.4 |
| 3.2 | Background task mechanism (FastAPI `BackgroundTasks`, or asyncio.create_task) triggered after a chat turn completes — does **not** block the `/chat` response | 2.4, 3.1 |
| 3.3 | Gemini prompt construction: pass ongoing chat context (from session messages) to generate a dynamic feedback question | 3.1, 1.5 |
| 3.4 | `GET /feedback-question/{session_id}` (or WS/poll) — side panel fetches latest generated question once ready | 3.2 |
| 3.5 | React `FeedbackPanel` component: distinct panel (separate from `ChatView`) polling/fetching and showing the Gemini-generated question | 3.4, 0.8 |

**Checkpoint 3**: sending a chat message returns immediately (latency unaffected); side panel populates a Gemini question shortly after, independently.

---

## Phase 4 — Feedback Persistence

**Goal**: component 5, closes the loop.

| Task | Description | Depends on |
|---|---|---|
| 4.1 | Answer input inside `FeedbackPanel` (React) tied to the current feedback question | 3.5 |
| 4.2 | `POST /feedback` endpoint — saves `{session_id, question, answer}` via `save_feedback` (1.5) | 1.5, 4.1 |
| 4.3 | Confirm FK linkage session → feedback entries queryable | 4.2, 1.3 |

**Checkpoint 4**: submit an answer, verify `FeedbackEntry` row exists and joins correctly to its `ChatSession`.

---

## Phase 5 — Integration Pass & Validation

| Task | Description | Depends on |
|---|---|---|
| 5.1 | Write `pytest` tests: session creation, chat round-trip (mock Nemotron), feedback round-trip (mock Gemini) | Phases 1–4 |
| 5.2 | Full manual run: backend via `python -m venv venv && pip install -r requirements.txt && uvicorn main:app --reload`, frontend via `cd frontend && npm install && npm run dev` → walk through key entry → chat → side panel → feedback answer → verify DB rows | All |
| 5.3 | Scope audit: diff implemented features against the 5-item V1 list; flag/remove anything extra (OAuth, scoring, etc.) | All |

**Checkpoint 5 (exit criteria)**: `pytest` green; manual walkthrough produces persisted chat + feedback rows; no out-of-scope features present.

---

## Execution Order Summary

```
Phase 0 (scaffold)
   └─▶ Phase 1 (data model)
          ├─▶ Phase 2 (key ingestion + chat)  ──▶ Phase 3 (Gemini panel, async) ──▶ Phase 4 (feedback persistence)
          └─▶ (1.5 repo functions feed 2.6, 3.3, 4.2 directly)
                                                                                         └─▶ Phase 5 (validation)
```

Phases 2→3→4 are sequential in practice (each depends on the previous producing session/message state), but tasks 1.x can run parallel to early 0.x once the DB engine (0.5) exists.

## Next Step

Run `/sc:implement` to execute this plan phase by phase, starting with Phase 0.
