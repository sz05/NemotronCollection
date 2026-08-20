"""Checkpoint 3: /chat must return before the Gemini feedback-question
generation completes, and the side panel must receive that question pushed
over WebSocket once the decoupled background task finishes -- no client
polling in the production path.

Runs a real uvicorn server (in-process, real TCP) rather than the in-process
ASGI transport used elsewhere, because Starlette's BackgroundTasks execute
*before* an in-process ASGI call returns -- only a real server demonstrates
that the client actually gets its response first.
"""

import asyncio
import json
import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import uvicorn
import websockets
from sqlalchemy import delete

from app.config import settings
from app.models import ChatSession, ScoreEvent
from main import app
from tests.conftest import TEST_EMAIL

GEMINI_DELAY_S = 1.0
PORT = 8765


async def _login(client: httpx.AsyncClient) -> str:
    """Dev-login on the live server; returns the auth cookie value for the
    WebSocket handshake (httpx keeps it for HTTP calls automatically)."""
    settings.dev_auth = True
    resp = await client.post("/auth/dev-login", json={"email": TEST_EMAIL})
    assert resp.status_code == 200, resp.text
    return client.cookies["access_token"]


@pytest.fixture
async def live_server():
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    yield f"http://127.0.0.1:{PORT}"
    server.should_exit = True
    await task


# Batched scoring returns summary + 4 sub-scores + one feedback question in a
# single call now; the WS push carries that question exactly as before.
_SCORE_RESULT = {
    "updated_summary": "The user greeted the assistant.",
    "scores": {"responsiveness": 50, "elaboration": 50, "development": 50, "progress": 50},
    "feedback_question": "How helpful was that reply?",
}


async def _slow_gemini(_context: dict) -> dict:
    await asyncio.sleep(GEMINI_DELAY_S)
    return _SCORE_RESULT


async def test_chat_returns_before_gemini_completes_and_ws_pushes_question(
    live_server, db_session
):
    # score_interval_turns=1 so a single turn crosses the scoring boundary.
    original_interval = settings.score_interval_turns
    settings.score_interval_turns = 1
    with (
        patch("app.routers.chat.send_chat_message", new=AsyncMock(return_value="hi there")),
        patch("app.services.scoring.score_and_summarize", new=_slow_gemini),
    ):
        async with httpx.AsyncClient(base_url=live_server) as client:
            token = await _login(client)
            session_id = (await client.post("/session")).json()["id"]

            # Connect the side panel's WebSocket before the chat turn happens,
            # exactly as the real frontend does (cookie rides the handshake).
            ws_url = f"ws://127.0.0.1:{PORT}/ws/feedback/{session_id}"
            ws_headers = {"Cookie": f"access_token={token}"}
            async with websockets.connect(ws_url, additional_headers=ws_headers) as ws:
                start = time.monotonic()
                chat_resp = await client.post(
                    "/chat",
                    json={"session_id": session_id, "message": "hello"},
                    headers={"X-Nemotron-Key": "nvapi-test"},
                )
                elapsed = time.monotonic() - start

                assert chat_resp.status_code == 200
                assert elapsed < GEMINI_DELAY_S / 2, (
                    f"/chat took {elapsed:.2f}s -- Gemini call appears to be blocking the response"
                )

                # Nothing pushed yet -- background generation is still "running".
                # Pushed messages only arrive once the background task finishes.
                # The socket is multiplexed: a {type:'score'} frame is pushed
                # alongside the question, so skip non-question frames.
                data = {}
                while "question" not in data:
                    pushed = await asyncio.wait_for(ws.recv(), timeout=GEMINI_DELAY_S + 2)
                    data = json.loads(pushed)
                assert data["question"] == "How helpful was that reply?"

            # GET fallback reflects the same state for non-WS clients/tests.
            fallback = (await client.get(f"/feedback-question/{session_id}")).json()
            assert fallback["question"] == "How helpful was that reply?"

    settings.score_interval_turns = original_interval
    # score_and_feedback wrote a ScoreEvent (FK to chat_session) -- clear the
    # child rows before deleting the session.
    await db_session.execute(delete(ScoreEvent).where(ScoreEvent.session_id == session_id))
    await db_session.execute(delete(ChatSession).where(ChatSession.id == session_id))
    await db_session.commit()


async def test_reconnecting_ws_gets_caught_up_with_existing_question(live_server, db_session):
    """A panel that connects *after* a question was already generated (e.g.
    on page reload) should be caught up immediately, not miss it."""
    original_interval = settings.score_interval_turns
    settings.score_interval_turns = 1
    with (
        patch("app.routers.chat.send_chat_message", new=AsyncMock(return_value="hi there")),
        patch(
            "app.services.scoring.score_and_summarize",
            new=AsyncMock(return_value={**_SCORE_RESULT, "feedback_question": "Q?"}),
        ),
    ):
        async with httpx.AsyncClient(base_url=live_server) as client:
            token = await _login(client)
            session_id = (await client.post("/session")).json()["id"]
            await client.post(
                "/chat",
                json={"session_id": session_id, "message": "hello"},
                headers={"X-Nemotron-Key": "nvapi-test"},
            )

            # Give the background task a moment to store the question before
            # this "late" connection arrives.
            for _ in range(20):
                data = (await client.get(f"/feedback-question/{session_id}")).json()
                if data["question"]:
                    break
                await asyncio.sleep(0.05)

            ws_url = f"ws://127.0.0.1:{PORT}/ws/feedback/{session_id}"
            ws_headers = {"Cookie": f"access_token={token}"}
            async with websockets.connect(ws_url, additional_headers=ws_headers) as ws:
                pushed = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
                assert pushed["question"] == "Q?"

    settings.score_interval_turns = original_interval
    # score_and_feedback wrote a ScoreEvent (FK to chat_session) -- clear the
    # child rows before deleting the session.
    await db_session.execute(delete(ScoreEvent).where(ScoreEvent.session_id == session_id))
    await db_session.execute(delete(ChatSession).where(ChatSession.id == session_id))
    await db_session.commit()
