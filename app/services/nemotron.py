"""Nemotron chat client (task 2.3).

Nemotron is called via NVIDIA's OpenAI-compatible chat completions API using
the caller-supplied API key. The key is accepted as a parameter on every call
and is never stored on this module or logged -- see task 2.2 for how it
reaches here from the request.

Uses urllib (stdlib) rather than httpx, run off the event loop via
asyncio.to_thread. This isn't the usual choice for an async FastAPI service,
but it's deliberate here: httpx requests to NVIDIA's hosted gateway
(integrate.api.nvidia.com) were hanging indefinitely under testing, while an
otherwise-identical urllib-based request against the same key/model
completed normally. The most likely explanation is the hosted gateway's
edge/CDN layer treating the two HTTP client implementations differently
(TLS/connection fingerprinting is a known cause of this kind of client-
specific behavior). Matching the client that's proven to work end-to-end
beats continuing to guess at payload fields.
"""

import asyncio
import json
import logging
import urllib.error
import urllib.request

from app.config import settings

logger = logging.getLogger(__name__)


class NemotronError(RuntimeError):
    """Raised when the Nemotron API call fails."""


def _post_chat_completions(api_key: str, messages: list[dict]) -> dict:
    """Blocking call, run off the event loop by send_chat_message."""
    payload = json.dumps(
        {
            "model": settings.nemotron_model,
            "messages": messages,
            "temperature": 0.6,  # NVIDIA's recommended setting for reasoning-mode Nemotron models
            "max_tokens": settings.nemotron_max_tokens,
        }
    ).encode()

    request = urllib.request.Request(
        f"{settings.nemotron_base_url}/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        # 180s (not 90) to accommodate the larger max_tokens: a reasoning model
        # writing multi-file code generates for a while. Raise this if you raise
        # NEMOTRON_MAX_TOKENS further, or big turns will time out mid-answer.
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        # exc.read() is Nemotron's own error body -- safe to log, no key in it.
        body = exc.read().decode(errors="replace")
        logger.warning("Nemotron API returned %s: %s", exc.code, body[:500])
        raise NemotronError(f"Nemotron API returned {exc.code}") from exc
    except urllib.error.URLError as exc:
        logger.warning("Nemotron API request failed: %r", exc.reason)
        raise NemotronError(f"Nemotron API request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        # urlopen doesn't always wrap a socket timeout in URLError.
        logger.warning("Nemotron API call timed out: %s", exc)
        raise NemotronError("Nemotron API timed out waiting for a response") from exc


async def send_chat_message(api_key: str, messages: list[dict]) -> str:
    """Send the full message history and return the assistant's reply text.

    `messages` is the OpenAI-style list of {"role", "content"} dicts already
    persisted for this session, including the newest user turn.
    """
    data = await asyncio.to_thread(_post_chat_completions, api_key, messages)

    try:
        choice = data["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError) as exc:
        raise NemotronError("Unexpected Nemotron API response shape") from exc

    # Some reasoning-model NIM endpoints leave "content" null and put the
    # text in "reasoning_content" instead (or truncate entirely if
    # finish_reason is "length"). Treat a present-but-empty content the same
    # as a missing one rather than letting None reach the response model.
    content = message.get("content") or message.get("reasoning_content")
    if not content:
        logger.warning(
            "Nemotron returned an empty reply (finish_reason=%r, message keys=%r)",
            choice.get("finish_reason"),
            list(message.keys()),
        )
        raise NemotronError(
            f"Nemotron returned an empty reply (finish_reason={choice.get('finish_reason')!r})"
        )

    return content


def _stream_chat_completions(api_key: str, messages: list[dict], queue, loop) -> None:
    """Blocking SSE reader, run in a worker thread. Parses the OpenAI-style
    `stream: true` response and pushes ("token", text) items onto `queue` as the
    ANSWER is produced (reasoning_content deltas are intentionally skipped -- we
    stream only the final answer). Ends with a None sentinel; on failure pushes
    ("error", message) first. Uses urllib to match the non-streaming client that
    works against NVIDIA's gateway (httpx hangs there -- see module docstring)."""
    payload = json.dumps(
        {
            "model": settings.nemotron_model,
            "messages": messages,
            "temperature": 0.6,
            "max_tokens": settings.nemotron_max_tokens,
            "stream": True,
        }
    ).encode()

    request = urllib.request.Request(
        f"{settings.nemotron_base_url}/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )

    def put(item) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, item)

    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            for raw in response:  # iterates the chunked stream line by line
                line = raw.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                try:
                    delta = json.loads(data)["choices"][0].get("delta", {})
                except (KeyError, IndexError, json.JSONDecodeError):
                    continue
                piece = delta.get("content")
                if piece:
                    put(("token", piece))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        logger.warning("Nemotron stream returned %s: %s", exc.code, body[:500])
        put(("error", f"Nemotron API returned {exc.code}"))
    except urllib.error.URLError as exc:
        logger.warning("Nemotron stream failed: %r", exc.reason)
        put(("error", f"Nemotron API request failed: {exc.reason}"))
    except TimeoutError:
        put(("error", "Nemotron API timed out waiting for a response"))
    except Exception as exc:  # noqa: BLE001 -- a thread crash must not hang the queue
        logger.exception("Unexpected Nemotron streaming failure")
        put(("error", f"Nemotron streaming failed: {exc}"))
    finally:
        put(None)


async def stream_chat_message(api_key: str, messages: list[dict]):
    """Async generator yielding the assistant's answer text in deltas as it's
    produced. Raises NemotronError if the stream errors. The blocking urllib
    reader runs in a thread and feeds an asyncio.Queue consumed here."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    future = loop.run_in_executor(
        None, _stream_chat_completions, api_key, messages, queue, loop
    )
    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            kind, value = item
            if kind == "error":
                raise NemotronError(value)
            yield value
    finally:
        # The thread always ends (it posts the None sentinel), so this returns
        # promptly on the normal path; guards against a leaked executor thread.
        if not future.done():
            try:
                await future
            except Exception:  # noqa: BLE001
                pass
