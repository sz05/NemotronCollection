"""Diagnose the Nemotron timeout by reproducing the app's EXACT request.

Run WITHOUT storing the key anywhere:

    NEMOTRON_KEY=nvapi-xxxx venv/bin/python scripts/diag_nemotron.py

It reuses app.config.settings (same model / base_url / max_tokens the app
uses) so this is a faithful reproduction of app/services/nemotron.py, plus a
streaming pass to separate "hung" from "just slow" (time-to-first-token).
"""

import json
import os
import time
import urllib.request

from app.config import settings

KEY = os.environ["NEMOTRON_KEY"]
MESSAGES = [{"role": "user", "content": "Say hello in one short sentence."}]
URL = f"{settings.nemotron_base_url}/chat/completions"

print(f"model={settings.nemotron_model}  max_tokens={settings.nemotron_max_tokens}")
print(f"url={URL}\n")


def build(stream: bool) -> urllib.request.Request:
    payload = {
        "model": settings.nemotron_model,
        "messages": MESSAGES,
        "temperature": 0.6,
        "max_tokens": settings.nemotron_max_tokens,
        "stream": stream,
    }
    return urllib.request.Request(
        URL,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {KEY}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if stream else "application/json",
        },
        method="POST",
    )


# 1) Non-streaming — exactly what the app does today (90s ceiling).
print("[1] non-streaming (app's current behavior)...")
t = time.time()
try:
    with urllib.request.urlopen(build(False), timeout=90) as r:
        data = json.loads(r.read())
    dt = time.time() - t
    ch = data["choices"][0]
    msg = ch["message"]
    content = msg.get("content") or msg.get("reasoning_content") or ""
    print(f"    OK in {dt:.1f}s  finish_reason={ch.get('finish_reason')!r}")
    print(f"    content_len={len(content)}  reasoning_only={bool(not msg.get('content') and msg.get('reasoning_content'))}")
except Exception as e:  # noqa: BLE001
    print(f"    FAILED after {time.time()-t:.1f}s: {e!r}")

# 2) Streaming — measures time-to-first-token vs total.
print("\n[2] streaming (time-to-first-token)...")
t = time.time()
first = None
n = 0
try:
    with urllib.request.urlopen(build(True), timeout=90) as r:
        for raw in r:
            line = raw.decode(errors="replace").strip()
            if line.startswith("data:") and line != "data: [DONE]":
                if first is None:
                    first = time.time() - t
                n += 1
    print(f"    first token in {first:.1f}s  total {time.time()-t:.1f}s  chunks={n}")
except Exception as e:  # noqa: BLE001
    print(f"    FAILED after {time.time()-t:.1f}s: {e!r}")
