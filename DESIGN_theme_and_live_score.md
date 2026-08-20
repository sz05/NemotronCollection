# Design — Locked Themes + Cumulative Live Score (socket push)

Extends `DESIGN.md` §2 (tasks/sessions), §3.2 (relevance guardrail), §3.4 (batched
scoring + feedback). Component + API design only; implement with `/sc:implement`.

## 1. Goals

1. **Live score push** — the running score reaches the browser over the socket the
   moment the 3–4-turn scoring batch finishes. No reload, no polling.
2. **Cumulative score** — each batch's score is *added* to a per-session running total
   that only grows. Individual rubric components are **not** shown to the user.
3. **New-chat theme choice** — clicking *New chat* asks: pick a theme (an existing seed
   task) **or** just talk about something random. Picking a task **locks** its `task_id`
   to that chat for its whole life; the relevance/similarity check then runs against that
   task. Random chats run with the guardrail fully disabled.

## 2. Key decisions (confirmed)

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Score is a **cumulative total** — `new_total = round(prior_total + batch_score, 2)`, monotonically increasing | User wants progress-style "keep adding" behaviour |
| D2 | **Hide components** — never sent over the socket, not rendered in the UI (kept in DB for audit only) | Requested |
| D3 | Theme source = **existing `Task` rows** from `GET /tasks` | Reuse seed tasks; no new content model |
| D4 | Task is **locked at session creation** and never mutated | `session.task_id` is already immutable — no new endpoint needed |
| D5 | Random chat = **guardrail fully disabled** (`task_id = null`) | Already the behaviour of unscoped sessions |
| D6 | Push over the **existing `/ws/feedback/{session_id}`** socket, using **typed** messages | One connection per session; `FeedbackConnectionManager` already broadcasts to all listeners |

## 3. Data model

No schema migration required.

- `ChatSession.live_score` (float) — **repurposed** from "latest batch score" to
  "cumulative running total". Existing rows keep their last value as the starting total;
  acceptable (no backfill).
- `ChatSession.score_components` (json) — still written for audit, **not** exposed to UI.
- `ScoreEvent.live_score` (per turn-batch) — stores the **batch delta** (the score for
  that batch), not the cumulative total, so the event log stays an accurate per-batch
  audit trail. The running total lives only on the session.

## 4. Socket contract (`/ws/feedback/{session_id}`)

The socket becomes multi-message. Messages are discriminated by presence of a field so
the **existing** feedback client keeps working unchanged.

| Message | Shape | Consumer |
|---------|-------|----------|
| Feedback question (unchanged) | `{ "question": "<str>" }` | `FeedbackPanel` (guards on `data.question`) |
| **New** — live score | `{ "type": "score", "value": <float> }` | `ScoreDisplay` (guards on `data.type === "score"`) |

`FeedbackPanel` ignores score messages (no `data.question`); `ScoreDisplay` ignores
question messages (no `data.type === "score"`). Both open their own socket to the same
endpoint; `FeedbackConnectionManager` already holds a **list** of sockets per session and
broadcasts to all, so two listeners is supported with zero backend change to fan-out.

## 5. Backend changes

### 5.1 `app/state.py` — `FeedbackConnectionManager`
Add a sibling of `push()`:
```python
async def push_score(self, session_id: uuid.UUID, value: float) -> None:
    # same broadcast/best-effort pattern as push()
    ...  # sends {"type": "score", "value": value} to every socket for the session
```
Keep `push()` (questions) exactly as-is.

### 5.2 `app/services/scoring.py` — `score_and_feedback`
- After computing `live = _live_score(scores)` (this is now the **batch delta**):
  - Read the prior cumulative total from the session already loaded for `prior_summary`
    (`prior_total = session.live_score if session else 0.0`).
  - `new_total = round(prior_total + live, 2)`.
  - `update_session_score(db, session_id, summary, scores, new_total)` — session stores
    the cumulative total.
  - `add_score_event(db, session_id, turn_index, {**scores, "context_snapshot": messages}, live)`
    — event stores the **batch delta** `live` (unchanged call, semantics clarified).
- After the DB commit, push the cumulative value:
  ```python
  await feedback_connection_manager.push_score(session_id, new_total)
  ```
  Placed alongside the existing `if question: ... push(...)` block. Failures stay swallowed
  by the existing try/except so scoring never crashes the background task.

> Note: `update_session_score` signature is unchanged — it still *overwrites*
> `live_score` with whatever value it's given. The cumulative arithmetic is done in
> `scoring.py`, keeping the repository generic. Single-process V1 turn ordering
> (chat gated by pending feedback) makes the read-add-write safe enough; a multi-worker
> deployment would need an atomic `UPDATE ... SET live_score = live_score + :delta`.

### 5.3 `app/routers/chat.py`
- No logic change to `/chat` — relevance guardrail already keys off `session.task_id`, so a
  locked task "just works" and a random (`task_id = null`) session already skips
  `evaluate()`.
- `GET /sessions/{session_id}/score` (`ScoreOut`) — keep returning `live_score` for the
  socket-less initial paint / reconnect catch-up. **Frontend renders only `live_score`,
  never `components`** (D2). Optionally drop `components` from `ScoreOut` later; not
  required.

### 5.4 Session creation — already sufficient
`POST /session` already accepts optional `task_id` (`SessionCreateRequest`). Locked theme =
create with `task_id`; random = create with none. No backend change.

## 6. Frontend changes

### 6.1 New-chat theme modal (new component, e.g. `NewChatModal.jsx`)
Triggered by the existing *New chat* action instead of creating a session immediately.

```
+-------------------------------------------+
|  Start a new chat                          |
|                                            |
|  ( ) Pick a theme                          |
|      [ Build a Wordle clone         v ]    |   <- GET /tasks
|  ( ) Just talk about something random      |
|                                            |
|              [ Cancel ]   [ Start ]        |
+-------------------------------------------+
```
- On mount: `GET /tasks` to fill the dropdown (title + difficulty).
- *Start*:
  - theme chosen → `POST /session { task_id }` → open that session (task **locked**).
  - random → `POST /session {}` (no task_id) → open unscoped session.
- The chat view shows the locked task title as a non-editable badge; there is **no** UI to
  change the task after creation (D4).

### 6.2 `ScoreDisplay.jsx` (new, small)
- Opens `new WebSocket(${WS_BASE_URL}/ws/feedback/${sessionId})`, filters
  `data.type === "score"`, renders **only** the numeric total (e.g. a "Score: 2.17" badge),
  animating on increase.
- Initial paint / reconnect: `GET /sessions/{id}/score` once for `live_score` so the badge
  isn't empty before the first socket message. **Ignores `components`.**
- Same lifecycle rules as `FeedbackPanel` (reconnect on `sessionId` change).

### 6.3 `FeedbackPanel.jsx`
- No functional change required (it already acts only on `data.question`). Optionally add an
  explicit `if (data.type === 'score') return` guard for clarity.

## 7. Sequence — a scoring turn

```
User -> POST /chat                          (turn N, on 3-4 boundary)
chat.py -> Nemotron -> reply -> return 200
BackgroundTasks -> score_and_feedback(...)
  Gemini score_and_summarize -> scores, summary, question?
  batch = _live_score(scores)
  new_total = prior_total + batch
  update_session_score(..., new_total)      # session.live_score = cumulative
  add_score_event(..., batch)               # event = delta
  push_score(session_id, new_total) --------> ws {type:'score', value: 2.17} -> ScoreDisplay
  if question: push(session_id, question) --> ws {question:'...'}            -> FeedbackPanel
```

## 8. Edge cases

- **Below turn boundary** — `score_and_feedback` still early-returns; no score push, badge
  unchanged. (Unchanged behaviour.)
- **Gemini failure** — caught; prior total preserved; no push. Badge holds last value.
- **Random chat** — no task, guardrail skipped, but scoring/score-push still runs
  (`task_description = ""`); the badge grows the same way. Confirm this is desired (scoring a
  themeless chat) at implement time — trivial to gate on `task_id` if not.
- **Reconnect mid-chat** — `ScoreDisplay` re-fetches `GET .../score` on socket open, so the
  cumulative total survives reload (this is the original bug, now fixed both ways).
- **Two sockets per session** — supported; `FeedbackConnectionManager` broadcasts to the
  list. Slightly more connections; acceptable at V1 scale (same single-process caveat as
  today).

## 9. Testing

- `test_scoring_cumulative` — two consecutive batches ⇒ `session.live_score` == sum of the
  two batch scores; each `ScoreEvent.live_score` == its own batch delta.
- `test_score_pushed_over_ws` — connect a WS client, drive a boundary turn, assert a
  `{type:'score'}` frame arrives with the cumulative value.
- `test_locked_task_relevance` — session created with `task_id`; off-topic message returns a
  `relevance_warning`; random session (`task_id=null`) never warns.
- Extend `tests/test_feedback_checkpoint.py` so the added score frame doesn't break the
  existing question-frame assertions.

## 10. Out of scope

- Score decay / reset, leaderboards driven by the cumulative total.
- Multi-worker atomicity (documented as a known single-process limitation).
- Changing a chat's task after creation (deliberately impossible — locked).
