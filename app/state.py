"""In-memory feedback-question state (supports task 3.2).

FeedbackQuestionStore holds the latest generated question per session, so a
freshly-(re)connected side panel can be caught up immediately.
ConnectionManager pushes new questions to connected side panels over
WebSocket the moment the background Gemini task finishes, instead of
clients polling for them.

Both are single-process, V1-scale only -- a multi-worker deployment would
need a shared store/pub-sub (e.g. Redis) instead.
"""

import asyncio
import uuid

from fastapi import WebSocket


class FeedbackQuestionStore:
    """Pending question per session, plus the conversation snapshot the
    question was generated from (persisted into feedback_entry on answer)."""

    def __init__(self) -> None:
        self._pending: dict[uuid.UUID, dict] = {}
        self._lock = asyncio.Lock()

    async def set(
        self, session_id: uuid.UUID, question: str, context: list[dict] | None = None
    ) -> None:
        async with self._lock:
            self._pending[session_id] = {"question": question, "context": context or []}

    async def get(self, session_id: uuid.UUID) -> str | None:
        async with self._lock:
            entry = self._pending.get(session_id)
            return entry["question"] if entry else None

    async def get_context(self, session_id: uuid.UUID) -> list[dict]:
        async with self._lock:
            entry = self._pending.get(session_id)
            return entry["context"] if entry else []

    async def clear(self, session_id: uuid.UUID) -> None:
        async with self._lock:
            self._pending.pop(session_id, None)


class FeedbackConnectionManager:
    """Tracks open /ws/feedback/{session_id} sockets and pushes questions."""

    def __init__(self) -> None:
        self._connections: dict[uuid.UUID, list[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, session_id: uuid.UUID, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.setdefault(session_id, []).append(websocket)

    async def disconnect(self, session_id: uuid.UUID, websocket: WebSocket) -> None:
        async with self._lock:
            sockets = self._connections.get(session_id)
            if sockets and websocket in sockets:
                sockets.remove(websocket)
            if sockets is not None and not sockets:
                self._connections.pop(session_id, None)

    async def push(self, session_id: uuid.UUID, question: str) -> None:
        async with self._lock:
            sockets = list(self._connections.get(session_id, []))
        for socket in sockets:
            try:
                await socket.send_json({"question": question})
            except Exception:
                # Best-effort push; a dead socket will be cleaned up by its
                # own receive loop hitting WebSocketDisconnect.
                pass

    async def push_score(self, session_id: uuid.UUID, value: float) -> None:
        """Broadcast the cumulative live score over the same per-session
        sockets. Typed ({"type": "score"}) so the feedback panel, which only
        acts on {"question": ...}, ignores it and a score listener can filter
        for it. Same best-effort semantics as push()."""
        async with self._lock:
            sockets = list(self._connections.get(session_id, []))
        for socket in sockets:
            try:
                await socket.send_json({"type": "score", "value": value})
            except Exception:
                pass


feedback_question_store = FeedbackQuestionStore()
feedback_connection_manager = FeedbackConnectionManager()
