"""Auth HTTP API: request OTP, verify, logout, current user."""
import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from storage.config import AUTH_EMAIL_ALLOWLIST
from storage.service import StorageService

from .deps import (
    clear_session_cookie,
    get_current_user,
    set_session_cookie,
)
from .mail import send_otp_email
from .store import (
    COOKIE_NAME,
    can_send_otp,
    create_guest_session,
    create_login_session,
    get_redis,
    is_guest_user_id,
    load_login_session,
    new_otp,
    normalize_email,
    store_otp,
    verify_otp,
)

router = APIRouter(prefix="/api")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class EmailIn(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)


class VerifyIn(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    code: str = Field(..., min_length=6, max_length=6)


def _storage(request: Request) -> StorageService:
    return request.app.state.storage


def _parse_email(raw: str) -> str:
    email = normalize_email(raw)
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="invalid email")
    return email


def _allowlisted(email: str) -> bool:
    raw = (AUTH_EMAIL_ALLOWLIST or "").strip()
    if not raw:
        return True
    allowed = {normalize_email(item) for item in raw.split(",") if item.strip()}
    return email in allowed


@router.post("/auth/request")
def request_code(body: EmailIn):
    email = _parse_email(body.email)
    if not _allowlisted(email):
        raise HTTPException(status_code=403, detail="this email is not on the allowlist")
    if not can_send_otp(email):
        raise HTTPException(status_code=429, detail="please wait before requesting another code")
    code = new_otp()
    store_otp(email, code)
    try:
        send_otp_email(email, code)
    except Exception as exc:
        get_redis().delete(f"otp_rate:{email}")
        raise HTTPException(status_code=502, detail=f"failed to send email: {exc}") from exc
    return {"ok": True}


@router.post("/auth/verify")
def verify_code(body: VerifyIn, request: Request, response: Response):
    email = _parse_email(body.email)
    if not body.code.isdigit():
        raise HTTPException(status_code=400, detail="invalid code")
    if not verify_otp(email, body.code):
        raise HTTPException(status_code=401, detail="invalid or expired code")
    current = load_login_session(request.cookies.get(COOKIE_NAME) or "")
    if current and is_guest_user_id(current["user_id"]):
        _storage(request).delete_user_sessions(current["user_id"])
    user = _storage(request).get_or_create_user(email)
    token = create_login_session(user["id"], user["email"])
    set_session_cookie(request, response, token)
    return user


@router.post("/auth/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE_NAME)
    clear_session_cookie(request, response, token)
    guest_token = create_guest_session()
    set_session_cookie(request, response, guest_token)
    return {"ok": True}


@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    uid = user["user_id"]
    return {
        "id": uid,
        "email": user.get("email") or "",
        "guest": is_guest_user_id(uid),
    }
