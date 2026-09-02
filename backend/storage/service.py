"""StorageService — the single gateway between the HTTP API / Agent Runtime
and the three storage layers.

    Frontend → HTTP API → StorageService → Agent / Redis / PostgreSQL / pgvector

Nothing outside StorageService may touch Redis/PostgreSQL directly, so the Agent
Runtime can reuse it unchanged for its own persistence (per BACKEND_INTEGRATION.md).
"""
import uuid
from typing import Iterator

import requests

from agent_client import AgentRuntime
from .cache import CacheLayer
from .config import CACHE_RECENT_MESSAGES
from .embeddings import generate_embedding
from .persistence import PersistenceLayer
from .semantic import SemanticLayer


class StorageService:
    """Unified entry point for all storage operations."""

    RECENT_MESSAGES = CACHE_RECENT_MESSAGES  # Redis cache window (最近 N 条)
    GUEST_ID_PREFIX = "guest:"
    GUEST_MAX_SESSIONS = 5

    def __init__(self, cache=None, persistence=None, semantic=None, agent=None):
        self.cache = cache or CacheLayer()
        self.persistence = persistence or PersistenceLayer()
        self.semantic = semantic or SemanticLayer()
        self.agent = agent or AgentRuntime()

    # -- Cache ------------------------------------------------------------

    def get_session(self, session_id: str) -> list:
        """Return session messages. Fast path: Redis cache; fall back to PostgreSQL.

        Because Redis only holds the recent window, a cold cache returns the full
        history from PostgreSQL and re-seeds Redis with the recent window.
        """
        cached = self.cache.get_session(session_id)
        if cached is not None:
            return cached
        history = self.persistence.get_history(session_id)
        if history is not None:
            self.cache.set_session(session_id, history[-self.RECENT_MESSAGES:])
            return history
        return []

    def update_session(self, session_id: str, message: dict) -> list:
        """Append a single message to the Redis cache window."""
        return self.cache.update_session(session_id, message)

    # -- Persistence ------------------------------------------------------

    def save_session(self, session_id: str, user_id: str, messages: list) -> None:
        """Upsert the full session history into PostgreSQL."""
        self.persistence.save_session(session_id, user_id, messages)

    def get_history(self, session_id: str):
        """Return the full session history from PostgreSQL (or None)."""
        return self.persistence.get_history(session_id)

    # -- Semantic ---------------------------------------------------------

    def store_memory(self, session_id: str, content: str, embedding: list) -> None:
        self.semantic.store_memory(session_id, content, embedding)

    def search_memory(self, query_embedding: list, limit: int = 5) -> list:
        return self.semantic.search_memory(query_embedding, limit)

    # -- Composite read ---------------------------------------------------

    def get_full_session(self, session_id: str, user_id: str) -> dict:
        """Session view for the GET API. Unknown ids look empty; others' sessions 404."""
        owner = self.persistence.get_user_id(session_id)
        if owner is not None and owner != user_id:
            return None
        messages = self.get_session(session_id) if owner is not None else []
        return {"session_id": session_id, "user_id": user_id, "messages": messages}

    def session_owned_by(self, session_id: str, user_id: str) -> bool:
        """True if the row is missing (first write) or belongs to this user."""
        owner = self.persistence.get_user_id(session_id)
        return owner is None or owner == user_id

    def get_or_create_user(self, email: str) -> dict:
        return self.persistence.get_or_create_user(email)

    # -- Session lifecycle ------------------------------------------------

    def list_user_sessions(self, user_id: str) -> list:
        """Newest-first list of this user's sessions for the sidebar."""
        return self.persistence.list_sessions(user_id)

    def _is_guest(self, user_id: str) -> bool:
        return (user_id or "").startswith(self.GUEST_ID_PREFIX)

    def _drop_cached_sessions(self, session_ids: list) -> None:
        for sid in session_ids:
            self.cache.delete_session(sid)

    def ensure_guest_room(self, user_id: str) -> None:
        """If this guest already has 5 sessions, delete the oldest until there is room for one more."""
        if not self._is_guest(user_id):
            return
        overflow = self.persistence.count_sessions(user_id) - (self.GUEST_MAX_SESSIONS - 1)
        if overflow <= 0:
            return
        deleted = self.persistence.delete_oldest_sessions(user_id, overflow)
        self._drop_cached_sessions(deleted)

    def delete_user_sessions(self, user_id: str) -> None:
        deleted = self.persistence.delete_sessions_for_user(user_id)
        self._drop_cached_sessions(deleted)

    def create_session(self, user_id: str) -> dict:
        """Pre-create an empty session row so it appears in the sidebar list.

        The first POST /sessions/{id}/messages will reuse this row via upsert.
        """
        self.ensure_guest_room(user_id)
        new_id = str(uuid.uuid4())
        self.persistence.save_session(new_id, user_id, [])
        return {"session_id": new_id, "user_id": user_id, "messages": []}

    # -- Core message flow (streaming) ------------------------------------

    def _last_user_text(self, messages: list) -> str:
        for msg in reversed(messages):
            if msg.get("role") == "user":
                return msg.get("content") or ""
        return ""

    def _persist_assistant(self, session_id: str, user_id: str, messages: list, assistant_message: dict) -> None:
        messages = messages + [assistant_message]
        self.cache.set_session(session_id, messages[-self.RECENT_MESSAGES:])
        self.persistence.save_session(session_id, user_id, messages)
        user_text = self._last_user_text(messages)
        try:
            embedding = generate_embedding(user_text)
            if embedding:
                self.semantic.store_memory(session_id, user_text, embedding)
        except Exception as exc:
            # Semantic layer failure must not block the main message flow.
            print(f"[storage] semantic memory skipped for session {session_id}: {exc}")

    def _relay_agent_events(self, session_id: str, user_id: str, events: Iterator[dict]) -> Iterator[dict]:
        """Forward Agent SSE events. Persist assistant only on done.

        interrupt is a successful pause: yield it and return, do not treat as
        agent_incomplete. pending.code is never stored in session history.
        """
        assistant_message = None
        try:
            for event in events:
                if event["type"] == "delta":
                    yield {"type": "delta", "delta": event["delta"]}
                elif event["type"] == "loop":
                    yield {"type": "loop", "event": event["event"]}
                elif event["type"] == "interrupt":
                    yield {
                        "type": "interrupt",
                        "run_id": event.get("run_id"),
                        "pending": event.get("pending") or [],
                    }
                    return
                elif event["type"] == "done":
                    assistant_message = event["message"]
                    break
                elif event["type"] == "error":
                    yield {
                        "type": "error",
                        "error": event.get("error", "agent_error"),
                        "detail": event.get("detail", ""),
                    }
                    return
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            detail = ""
            if exc.response is not None:
                try:
                    detail = exc.response.text
                except Exception:
                    detail = str(exc)
            yield {
                "type": "error",
                "error": "agent_http_error",
                "detail": detail or str(exc),
                "status": status,
            }
            return
        except requests.RequestException as exc:
            yield {"type": "error", "error": "agent_unreachable", "detail": str(exc)}
            return
        except Exception as exc:  # unexpected — surface instead of faking a reply
            yield {"type": "error", "error": "agent_error", "detail": str(exc)}
            return

        if not assistant_message:
            yield {"type": "error", "error": "agent_incomplete",
                   "detail": "stream ended without done event"}
            return

        history = self.get_session(session_id)
        self._persist_assistant(session_id, user_id, history, assistant_message)
        yield {
            "type": "done",
            "message": assistant_message,
            "session_id": session_id,
            "user_id": user_id,
        }

    def stream_user_message(self, session_id: str, user_id: str, message: str) -> Iterator[dict]:
        """Run a user message through the full pipeline, streaming Agent output.

        Yields dict events consumed by the API layer (translated to SSE):

          - {"type": "delta", "delta": "..."}    0..N  — Agent incremental text
          - {"type": "interrupt", "run_id", "pending"}  0 or 1 — HITL pause
          - {"type": "done",  "message": {...},
             "session_id": ..., "user_id": ...}  1 if the run finished
          - {"type": "error", "error": "...",
             "detail": "..."}                   0 or 1 — Agent failure

        Storage flow:
          1. Load history (Redis cache → PG fallback), append user message.
          2. Persist user message to Redis + PG.
          3. Stream from Agent (POST /complete/stream).
          4. On done: append assistant, persist, semantic memory.
          5. On interrupt: yield it, do not persist an assistant.
          6. On Agent failure: assistant is NOT persisted. The user message
             stays in PG — that is correct (user did send it).

        No mock fallback: Agent failures surface as `error` events so the
        frontend can show "send failed" and the caller never silently fakes
        a reply.
        """
        # 1-2. Load history + append user + persist.
        if self.persistence.get_user_id(session_id) is None:
            self.ensure_guest_room(user_id)
        history = self.get_session(session_id)
        messages = history + [{"role": "user", "content": message}]
        self.cache.set_session(session_id, messages[-self.RECENT_MESSAGES:])
        self.persistence.save_session(session_id, user_id, messages)

        yield from self._relay_agent_events(
            session_id,
            user_id,
            self.agent.stream(session_id=session_id, user_id=user_id, messages=messages),
        )

    def stream_resume(self, session_id: str, user_id: str, run_id: str, results: list) -> Iterator[dict]:
        """Continue a HITL run after the browser eval'd (or rejected) pending JS."""
        yield from self._relay_agent_events(
            session_id,
            user_id,
            self.agent.resume_stream(run_id, results),
        )

