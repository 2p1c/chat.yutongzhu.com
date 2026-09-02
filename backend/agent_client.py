"""HTTP client for the TypeScript Agent container.

Wraps POST /complete, POST /complete/stream, and POST /resume/stream.
No mock fallback — Agent failures propagate as HTTPError so the caller decides.
"""
import json
from typing import Iterator

import requests

from storage.config import AGENT_URL

# LLM + tool loops can be slow; 120s is generous without being forever.
REQUEST_TIMEOUT_SECONDS = 120


def _utf8_text(value: str) -> str:
    # JS string.slice can split an emoji into a lone UTF-16 surrogate; Python
    # json.loads keeps it, then Starlette's SSE encode('utf-8') raises.
    return value.encode("utf-8", "replace").decode("utf-8")


def _iter_sse(response: requests.Response) -> Iterator[dict]:
    """Parse Agent SSE. Yields loop / delta / done / interrupt / error.

    `event: interrupt` ends the stream without a done event — that is the HITL
    contract, not an error. Loop events with type "interrupt" are ignored here.
    """
    event_name = "message"
    # Keep raw bytes — Agent's Content-Type lacks charset so requests
    # would otherwise default to Latin-1 and produce mojibake on UTF-8.
    for raw_line in response.iter_lines():
        if raw_line is None:
            continue
        line = raw_line.decode("utf-8") if isinstance(raw_line, (bytes, bytearray)) else raw_line
        if not line:
            event_name = "message"
            continue
        if line.startswith("event:"):
            event_name = line[len("event:"):].strip()
            continue
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if not payload or payload == "[DONE]":
            event_name = "message"
            continue
        try:
            evt = json.loads(payload)
        except json.JSONDecodeError:
            event_name = "message"
            continue
        if event_name == "loop":
            yield {"type": "loop", "event": evt}
            event_name = "message"
            continue
        if event_name == "interrupt":
            yield {
                "type": "interrupt",
                "run_id": evt.get("run_id") if isinstance(evt, dict) else None,
                "pending": evt.get("pending") if isinstance(evt, dict) else [],
            }
            return
        if event_name == "error" or (isinstance(evt, dict) and evt.get("error")):
            yield {
                "type": "error",
                "error": evt.get("error", "agent_error") if isinstance(evt, dict) else "agent_error",
                "detail": evt.get("detail", "") if isinstance(evt, dict) else str(evt),
            }
            return
        if isinstance(evt, dict) and "delta" in evt:
            delta = evt["delta"]
            if isinstance(delta, str):
                delta = _utf8_text(delta)
            yield {"type": "delta", "delta": delta}
        elif isinstance(evt, dict) and evt.get("done") and isinstance(evt.get("message"), dict):
            message = dict(evt["message"])
            content = message.get("content")
            if isinstance(content, str):
                message["content"] = _utf8_text(content)
            yield {"type": "done", "message": message}
        event_name = "message"


class AgentRuntime:
    """HTTP client for the Agent container."""

    def __init__(self, url: str = AGENT_URL):
        self.url = url.rstrip("/")

    def complete(self, *, session_id: str, user_id: str, messages: list) -> dict:
        """One-shot: POST /complete. Returns {role, content}. Raises on 5xx."""
        r = requests.post(
            f"{self.url}/complete",
            json={"session_id": session_id, "user_id": user_id, "messages": messages},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        r.raise_for_status()
        return r.json()

    def stream(self, *, session_id: str, user_id: str, messages: list) -> Iterator[dict]:
        """Streaming: POST /complete/stream. Yields dicts:

          - {"type": "loop",  "event": {...}}              0..N  (local Agent only)
          - {"type": "delta", "delta": "..."}              0..N
          - {"type": "interrupt", "run_id", "pending"}     0 or 1 (HITL; no done)
          - {"type": "done",  "message": {...}}            1 if the run finished

        Stops early on Agent 5xx (the exception propagates to the caller).
        Older Agent images that never send `event: loop` still work.
        """
        with requests.post(
            f"{self.url}/complete/stream",
            json={"session_id": session_id, "user_id": user_id, "messages": messages},
            timeout=REQUEST_TIMEOUT_SECONDS,
            stream=True,
        ) as r:
            r.raise_for_status()
            yield from _iter_sse(r)

    def resume_stream(self, run_id: str, results: list) -> Iterator[dict]:
        """Streaming: POST /resume/stream. Same event shapes as stream()."""
        with requests.post(
            f"{self.url}/resume/stream",
            json={"run_id": run_id, "results": results},
            timeout=REQUEST_TIMEOUT_SECONDS,
            stream=True,
        ) as r:
            r.raise_for_status()
            yield from _iter_sse(r)
