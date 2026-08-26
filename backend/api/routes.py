"""HTTP API for the chat storage service.

    Frontend → HTTP API → StorageService → Redis / PostgreSQL / pgvector

This layer only ever talks to StorageService — never to Redis/PostgreSQL directly.

TODO(Future Agent API):
    POST /api/agent/chat  — the Agent Runtime entry point will live here and
    reuse StorageService for persistence. Not implemented in this phase.
"""
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from storage.config import DEFAULT_USER_ID
from storage.service import StorageService

router = APIRouter(prefix="/api")


class MessageIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    user_id: str = DEFAULT_USER_ID


class SessionCreate(BaseModel):
    user_id: str = DEFAULT_USER_ID


def _storage(request: Request) -> StorageService:
    return request.app.state.storage


def _require_uuid(session_id: str) -> str:
    try:
        return str(UUID(session_id))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"invalid session_id: {session_id!r}")


@router.get("/health")
def health(request: Request):
    """Liveness check for the storage service."""
    return {"status": "ok"}


@router.post("/sessions")
def create_session(body: SessionCreate, request: Request):
    """POST /api/sessions — pre-create an empty session row.

    Returns the new session_id so the sidebar can switch to it without waiting
    for the first message.
    """
    return _storage(request).create_session(body.user_id)


@router.get("/users/{user_id}/sessions")
def list_user_sessions(user_id: str, request: Request):
    """GET /api/users/{user_id}/sessions — list a user's sessions, newest first.

    Each item: {session_id, title (first user message), created_at, updated_at,
    message_count}. Title is None for sessions with no user message yet.
    """
    return _storage(request).list_user_sessions(user_id)


@router.get("/sessions/{session_id}")
def get_session(session_id: str, request: Request):
    """GET /api/sessions/{session_id} — fetch the current session."""
    _require_uuid(session_id)
    return _storage(request).get_full_session(session_id)


@router.post("/sessions/{session_id}/messages")
def post_message(session_id: str, body: MessageIn, request: Request):
    """POST /api/sessions/{session_id}/messages — send one message.

    Runs the message through the full storage pipeline (Redis → PostgreSQL →
    pgvector) and returns the updated session.
    """
    _require_uuid(session_id)
    return _storage(request).handle_user_message(session_id, body.user_id, body.message)
