"""HTTP client for the TypeScript Agent container.

Wraps POST /complete (one-shot) and POST /complete/stream (SSE). No mock
fallback — Agent failures propagate as HTTPError so the caller decides.
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

          - {"type": "delta", "delta": "..."}    (0..N)
          - {"type": "done",  "message": {...}}  (exactly 1, last)

        Stops early on Agent 5xx (the exception propagates to the caller).
        """
        with requests.post(
            f"{self.url}/complete/stream",
            json={"session_id": session_id, "user_id": user_id, "messages": messages},
            timeout=REQUEST_TIMEOUT_SECONDS,
            stream=True,
        ) as r:
            r.raise_for_status()
            # Keep raw bytes — Agent's Content-Type lacks charset so requests
            # would otherwise default to Latin-1 and produce mojibake on UTF-8.
            for raw_line in r.iter_lines():
                if raw_line is None:
                    continue
                line = raw_line.decode("utf-8") if isinstance(raw_line, (bytes, bytearray)) else raw_line
                if not line or not line.startswith("data:"):
                    continue
                payload = line[len("data:"):].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    evt = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if "delta" in evt:
                    delta = evt["delta"]
                    if isinstance(delta, str):
                        delta = _utf8_text(delta)
                    yield {"type": "delta", "delta": delta}
                elif evt.get("done") and isinstance(evt.get("message"), dict):
                    message = dict(evt["message"])
                    content = message.get("content")
                    if isinstance(content, str):
                        message["content"] = _utf8_text(content)
                    yield {"type": "done", "message": message}
