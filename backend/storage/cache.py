"""Cache Layer — Redis.

Stores the current session's recent messages under a single Hash key:

    session:{session_id}  ->  { "messages": "[...json array...]" }

TTL: 600 seconds (spec section 11). Redis only holds the recent window; the full
history always lives in PostgreSQL.
"""
import json
import uuid

import redis

from .config import REDIS_URL

# Delete the lock only if it still holds our token: after a TTL expiry another
# request may own it, and a plain DEL would release their lock.
_RELEASE_LOCK = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


class CacheLayer:
    """Redis-backed cache for active session messages."""

    KEY_TTL_SECONDS = 600  # spec: TTL = 600s
    MESSAGES_FIELD = "messages"

    def __init__(self, redis_url: str = REDIS_URL):
        self.redis = redis.Redis.from_url(redis_url, decode_responses=True)
        self._release_lock = self.redis.register_script(_RELEASE_LOCK)

    # -- internal helpers -------------------------------------------------

    def _key(self, session_id: str) -> str:
        # The only key shape this project uses (spec section 11).
        return f"session:{session_id}"

    def _write(self, session_id: str, messages: list) -> None:
        self.redis.hset(
            self._key(session_id),
            self.MESSAGES_FIELD,
            json.dumps(messages, ensure_ascii=False),
        )
        self.redis.expire(self._key(session_id), self.KEY_TTL_SECONDS)

    # -- required API -----------------------------------------------------

    def get_session(self, session_id: str):
        """Return the cached messages (list), or None if the key does not exist."""
        raw = self.redis.hget(self._key(session_id), self.MESSAGES_FIELD)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def update_session(self, session_id: str, new_message: dict) -> list:
        """Get the current cached messages, append `new_message`, write back, reset TTL."""
        messages = self.get_session(session_id) or []
        messages = messages + [new_message]
        self._write(session_id, messages)
        return messages

    def set_session(self, session_id: str, messages: list) -> list:
        """Replace the cached messages and reset TTL (used to seed from PostgreSQL)."""
        self._write(session_id, messages)
        return messages

    def delete_session(self, session_id: str) -> None:
        self.redis.delete(self._key(session_id))

    # -- distributed lock ---------------------------------------------------

    def acquire_lock(self, key: str, ttl_seconds: int) -> str | None:
        """SET NX EX: returns a token if acquired, None if someone else holds it."""
        token = uuid.uuid4().hex
        if self.redis.set(key, token, nx=True, ex=ttl_seconds):
            return token
        return None

    def release_lock(self, key: str, token: str) -> None:
        self._release_lock(keys=[key], args=[token])
