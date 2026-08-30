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

    def create_session(self, user_id: str) -> dict:
        """Pre-create an empty session row so it appears in the sidebar list.

        The first POST /sessions/{id}/messages will reuse this row via upsert.
        """
        new_id = str(uuid.uuid4())
        self.persistence.save_session(new_id, user_id, [])
        return {"session_id": new_id, "user_id": user_id, "messages": []}

    def list_user_sessions(self, user_id: str) -> list:
        """Newest-first list of this user's sessions for the sidebar."""
        return self.persistence.list_sessions(user_id)

    # -- Core message flow (streaming) ------------------------------------

    def stream_user_message(self, session_id: str, user_id: str, message: str) -> Iterator[dict]:
        """Run a user message through the full pipeline, streaming Agent output.

        Yields dict events consumed by the API layer (translated to SSE):

          - {"type": "delta", "delta": "..."}    0..N  — Agent incremental text
          - {"type": "done",  "message": {...},
             "session_id": ..., "user_id": ...}  exactly 1
          - {"type": "error", "error": "...",
             "detail": "..."}                   0 or 1 — Agent failure

        Storage flow (mirrors the legacy spec):
          1. Load history (Redis cache → PG fallback), append user message.
          2. Persist user message to Redis + PG.
          3. Stream from Agent (POST /complete/stream).
          4. On done event: append assistant, persist, semantic memory.
          5. On Agent failure: assistant is NOT persisted. The user message
             stays in PG — that is correct (user did send it).

        No mock fallback: Agent failures surface as `error` events so the
        frontend can show "send failed" and the caller never silently fakes
        a reply.
        """
        # 1-2. Load history + append user + persist.
        history = self.get_session(session_id)
        messages = history + [{"role": "user", "content": message}]
        self.cache.set_session(session_id, messages[-self.RECENT_MESSAGES:])
        self.persistence.save_session(session_id, user_id, messages)

        # 3. Stream from Agent.
        assistant_message = None
        try:
            for event in self.agent.stream(
                session_id=session_id, user_id=user_id, messages=messages,
            ):
                if event["type"] == "delta":
                    yield {"type": "delta", "delta": event["delta"]}
                elif event["type"] == "loop":
                    yield {"type": "loop", "event": event["event"]}
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

        # 4. Persist assistant + semantic memory (best-effort).
        messages = messages + [assistant_message]
        self.cache.set_session(session_id, messages[-self.RECENT_MESSAGES:])
        self.persistence.save_session(session_id, user_id, messages)
        try:
            embedding = generate_embedding(message)
            if embedding:
                self.semantic.store_memory(session_id, message, embedding)
        except Exception as exc:
            # Semantic layer failure must not block the main message flow.
            print(f"[storage] semantic memory skipped for session {session_id}: {exc}")

        # 5. Final done event.
        yield {
            "type": "done",
            "message": assistant_message,
            "session_id": session_id,
            "user_id": user_id,
        }

