"""/chat/stream: the SSE endpoint emits answer tokens then a done frame, and
persists the turn only after the full answer streams. Nemotron is mocked."""

import json
import uuid

from sqlalchemy import delete


async def test_chat_stream_emits_tokens_and_persists(auth_client, db_session, monkeypatch):
    sid = (await auth_client.post("/session", json={})).json()["id"]

    async def fake_stream(api_key, messages):
        for piece in ["Hel", "lo!"]:
            yield piece

    # Patch the name as imported into the chat router.
    monkeypatch.setattr("app.routers.chat.stream_chat_message", fake_stream)

    body = ""
    async with auth_client.stream(
        "POST",
        "/chat/stream",
        json={"session_id": sid, "message": "hi"},
        headers={"X-Nemotron-Key": "nvapi-test"},  # bypass stored-key lookup
    ) as resp:
        assert resp.status_code == 200
        async for chunk in resp.aiter_text():
            body += chunk

    events = [json.loads(l[5:].strip()) for l in body.split("\n") if l.startswith("data:")]
    types = [e["type"] for e in events]
    assert "token" in types and types[-1] == "done"
    assert "".join(e["content"] for e in events if e["type"] == "token") == "Hello!"

    # The completed turn was persisted (user + assistant) after the stream.
    detail = (await auth_client.get(f"/sessions/{sid}")).json()
    assert detail["messages"][-2:] == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "Hello!"},
    ]

    from app.models import ChatSession

    await db_session.execute(delete(ChatSession).where(ChatSession.id == uuid.UUID(sid)))
    await db_session.commit()
