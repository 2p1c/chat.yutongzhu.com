"""HTTP API for the chat storage service.

    Frontend → HTTP API → StorageService → Agent / Redis / PostgreSQL / pgvector

This layer only ever talks to StorageService — never to Redis/PostgreSQL directly.

POST /api/sessions/{session_id}/messages and POST /api/sessions/{session_id}/resume
stream SSE: the Agent runtime may take seconds; the browser renders tokens as
they arrive. A HITL pause is `event: interrupt` with no trailing [DONE].
"""
import json
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from auth.deps import get_current_user
from storage.service import StorageService

router = APIRouter(prefix="/api")


class MessageIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)


class ResumeResultIn(BaseModel):
    tool_call_id: str
    content: str
    outcome: Literal["ok", "error", "rejected"]


class ResumeIn(BaseModel):
    run_id: str = Field(..., min_length=1)
    results: list[ResumeResultIn]


def _storage(request: Request) -> StorageService:
    return request.app.state.storage


def _require_uuid(session_id: str) -> str:
    try:
        return str(UUID(session_id))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"invalid session_id: {session_id!r}")


def _user_id(user: dict) -> str:
    return user["user_id"]


_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",  # disable proxy buffering (nginx)
    "Content-Encoding": "identity",
    "Connection": "keep-alive",
}


def _sse_chunks(events):
    """Translate StorageService events into SSE bytes. interrupt has no [DONE]."""
    for event in events:
        if event["type"] == "loop":
            yield (
                "event: loop\n"
                f"data: {json.dumps(event['event'], ensure_ascii=False)}\n\n"
            )
        elif event["type"] == "delta":
            yield f"data: {json.dumps({'delta': event['delta']}, ensure_ascii=False)}\n\n"
        elif event["type"] == "interrupt":
            yield (
                "event: interrupt\n"
                f"data: {json.dumps({'run_id': event.get('run_id'), 'pending': event.get('pending') or []}, ensure_ascii=False)}\n\n"
            )
            return
        elif event["type"] == "done":
            yield f"data: {json.dumps({'done': True, 'message': event['message']}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        elif event["type"] == "error":
            payload = {
                "error": event["error"],
                "detail": event.get("detail", ""),
            }
            if event.get("status") is not None:
                payload["status"] = event["status"]
            yield f"event: error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            break  # errors are terminal; close the stream


@router.get("/health")
def health(request: Request):
    """Liveness check for the storage service."""
    return {"status": "ok"}


@router.post("/sessions")
def create_session(request: Request, user: dict = Depends(get_current_user)):
    """POST /api/sessions — pre-create an empty session row for the current user."""
    return _storage(request).create_session(_user_id(user))


@router.get("/me/sessions")
def list_my_sessions(request: Request, user: dict = Depends(get_current_user)):
    """GET /api/me/sessions — list the current user's sessions, newest first."""
    return _storage(request).list_user_sessions(_user_id(user))


@router.get("/sessions/{session_id}")
def get_session(session_id: str, request: Request, user: dict = Depends(get_current_user)):
    """GET /api/sessions/{session_id} — fetch the current session."""
    _require_uuid(session_id)
    data = _storage(request).get_full_session(session_id, _user_id(user))
    if data is None:
        raise HTTPException(status_code=404, detail="session not found")
    return data


@router.post("/sessions/{session_id}/messages")
def post_message(
    session_id: str,
    body: MessageIn,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """POST /api/sessions/{session_id}/messages — send one message (SSE stream).

    SSE event shapes:
      - event: loop / data: {type, step, ...}                     0..N (local Agent)
      - data: {"delta": "..."}                                    0..N
      - event: interrupt / data: {"run_id", "pending"}            0 or 1 (no [DONE])
      - data: {"done": true, "message": {role, content, ...}}     1 if finished
      - data: [DONE]                                              terminator (done only)
      - event: error / data: {"error": "...", "detail": "..."}    0..1
    """
    _require_uuid(session_id)
    storage = _storage(request)
    uid = _user_id(user)
    if not storage.session_owned_by(session_id, uid):
        raise HTTPException(status_code=404, detail="session not found")

    return StreamingResponse(
        _sse_chunks(storage.stream_user_message(session_id, uid, body.message)),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.post("/sessions/{session_id}/resume")
def post_resume(
    session_id: str,
    body: ResumeIn,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """POST /api/sessions/{session_id}/resume — continue a HITL run (SSE stream).

    Same SSE shapes as POST .../messages (loop / delta / interrupt / done / error).
    """
    _require_uuid(session_id)
    storage = _storage(request)
    uid = _user_id(user)
    if not storage.session_owned_by(session_id, uid):
        raise HTTPException(status_code=404, detail="session not found")

    results = [item.model_dump() for item in body.results]
    return StreamingResponse(
        _sse_chunks(storage.stream_resume(session_id, uid, body.run_id, results)),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
