"""Redis-backed OTP codes and login sessions.

Keys (separate from the chat cache window):
    otp:{email}       -> {code, attempts}   TTL 10 minutes
    otp_rate:{email}  -> 1                  TTL 60 seconds (send throttle)
    sess:{token}      -> {user_id, email}   TTL 30 days
"""
import json
import secrets

import redis

from storage.config import REDIS_URL

OTP_TTL_SECONDS = 10 * 60
OTP_SEND_INTERVAL_SECONDS = 60
OTP_MAX_ATTEMPTS = 5
SESSION_TTL_SECONDS = 30 * 24 * 60 * 60
COOKIE_NAME = "chat_session"

_redis = None


def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    return _redis


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def new_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def can_send_otp(email: str) -> bool:
    """True if this address has not requested a code in the last minute."""
    return bool(
        get_redis().set(
            f"otp_rate:{email}",
            "1",
            nx=True,
            ex=OTP_SEND_INTERVAL_SECONDS,
        )
    )


def store_otp(email: str, code: str) -> None:
    get_redis().setex(
        f"otp:{email}",
        OTP_TTL_SECONDS,
        json.dumps({"code": code, "attempts": 0}),
    )


def verify_otp(email: str, code: str) -> bool:
    r = get_redis()
    key = f"otp:{email}"
    raw = r.get(key)
    if not raw:
        return False
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        r.delete(key)
        return False
    attempts = int(data.get("attempts") or 0)
    if attempts >= OTP_MAX_ATTEMPTS:
        r.delete(key)
        return False
    if str(data.get("code") or "") != str(code).strip():
        data["attempts"] = attempts + 1
        ttl = r.ttl(key)
        r.setex(key, ttl if ttl and ttl > 0 else OTP_TTL_SECONDS, json.dumps(data))
        return False
    r.delete(key)
    return True


def create_login_session(user_id: str, email: str) -> str:
    token = secrets.token_urlsafe(32)
    get_redis().setex(
        f"sess:{token}",
        SESSION_TTL_SECONDS,
        json.dumps({"user_id": user_id, "email": email}),
    )
    return token


def load_login_session(token: str):
    if not token:
        return None
    raw = get_redis().get(f"sess:{token}")
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not data.get("user_id"):
        return None
    get_redis().expire(f"sess:{token}", SESSION_TTL_SECONDS)
    return data


def delete_login_session(token: str) -> None:
    if token:
        get_redis().delete(f"sess:{token}")
