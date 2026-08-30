"""FastAPI auth helpers: current user + cookie flags."""
from fastapi import Cookie, HTTPException, Request, Response

from .store import (
    COOKIE_NAME,
    SESSION_TTL_SECONDS,
    delete_login_session,
    load_login_session,
)


def cookie_secure(request: Request) -> bool:
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    return proto == "https"


def set_session_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=SESSION_TTL_SECONDS,
        secure=cookie_secure(request),
        path="/",
    )


def clear_session_cookie(request: Request, response: Response, token: str | None) -> None:
    delete_login_session(token or "")
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        samesite="lax",
        secure=cookie_secure(request),
    )


def get_current_user(
    request: Request,
    chat_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
) -> dict:
    data = load_login_session(chat_session or "")
    if not data:
        raise HTTPException(status_code=401, detail="not authenticated")
    request.state.session_token = chat_session
    return data
