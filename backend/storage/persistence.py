"""Persistence Layer — PostgreSQL.

Permanently stores the full session history in the `sessions` table
(messages as JSONB). PostgreSQL is the source of truth: if the Redis cache
expires, sessions are recovered from here.
"""
import json
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

from .config import DATABASE_URL

EMPTY_USAGE = {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
    "last_prompt_tokens": 0,
}


def normalize_usage(raw) -> dict:
    """Coerce Agent/DB usage objects into non-negative ints."""
    if not isinstance(raw, dict):
        return dict(EMPTY_USAGE)

    def n(key: str) -> int:
        v = raw.get(key, 0)
        try:
            v = int(v)
        except (TypeError, ValueError):
            return 0
        return max(0, v)

    prompt = n("prompt_tokens")
    completion = n("completion_tokens")
    total = n("total_tokens") or prompt + completion
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "last_prompt_tokens": n("last_prompt_tokens"),
    }


class PersistenceLayer:
    """CRUD for the `sessions` table."""

    def __init__(self, conninfo: str = DATABASE_URL):
        self.conninfo = conninfo

    def _connect(self):
        return psycopg.connect(self.conninfo, row_factory=dict_row)

    def save_session(self, session_id: str, user_id: str, messages: list) -> None:
        """INSERT when the session is new, UPDATE when it already exists (upsert on PK)."""
        now = datetime.now(timezone.utc)
        payload = json.dumps(messages, ensure_ascii=False)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO sessions (id, user_id, messages, created_at, updated_at)
                    VALUES (%s, %s, %s::jsonb, %s, %s)
                    ON CONFLICT (id) DO UPDATE
                        SET messages   = EXCLUDED.messages,
                            updated_at = EXCLUDED.updated_at
                    """,
                    (session_id, user_id, payload, now, now),
                )

    def get_history(self, session_id: str):
        """Return the full messages array, or None if the session is unknown."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT messages FROM sessions WHERE id = %s", (session_id,))
                row = cur.fetchone()
        return row["messages"] if row else None

    def get_token_usage(self, session_id: str) -> dict:
        """Return this session's accumulated token usage, or zeros if unknown."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT token_usage FROM sessions WHERE id = %s", (session_id,))
                row = cur.fetchone()
        if not row:
            return dict(EMPTY_USAGE)
        return normalize_usage(row["token_usage"])

    def add_token_usage(self, session_id: str, delta, last_prompt_tokens: int | None = None) -> dict:
        """Add one Agent run's usage onto the session total. Returns the new total.

        last_prompt_tokens is this request's context occupancy (not accumulated).
        Pass 0 after /compact so the frontend drops the 80% hint.
        """
        d = normalize_usage(delta)
        zero_delta = (
            d["prompt_tokens"] == 0
            and d["completion_tokens"] == 0
            and d["total_tokens"] == 0
        )
        if zero_delta and last_prompt_tokens is None:
            return self.get_token_usage(session_id)
        last = (
            d["prompt_tokens"]
            if last_prompt_tokens is None
            else max(0, int(last_prompt_tokens))
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE sessions
                    SET token_usage = jsonb_build_object(
                            'prompt_tokens',
                            COALESCE((token_usage->>'prompt_tokens')::int, 0) + %s,
                            'completion_tokens',
                            COALESCE((token_usage->>'completion_tokens')::int, 0) + %s,
                            'total_tokens',
                            COALESCE((token_usage->>'total_tokens')::int, 0) + %s,
                            'last_prompt_tokens',
                            %s
                        ),
                        updated_at = %s
                    WHERE id = %s
                    RETURNING token_usage
                    """,
                    (
                        d["prompt_tokens"],
                        d["completion_tokens"],
                        d["total_tokens"],
                        last,
                        datetime.now(timezone.utc),
                        session_id,
                    ),
                )
                row = cur.fetchone()
        if not row:
            return dict(EMPTY_USAGE)
        return normalize_usage(row["token_usage"])

    def get_llm_messages(self, session_id: str):
        """Return compacted Agent history, or None if the session uses display messages."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT llm_messages FROM sessions WHERE id = %s",
                    (session_id,),
                )
                row = cur.fetchone()
        if not row:
            return None
        raw = row["llm_messages"]
        return raw if isinstance(raw, list) else None

    def set_llm_messages(self, session_id: str, messages: list) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE sessions
                    SET llm_messages = %s::jsonb, updated_at = %s
                    WHERE id = %s
                    """,
                    (json.dumps(messages, ensure_ascii=False), datetime.now(timezone.utc), session_id),
                )

    def clear_llm_messages(self, session_id: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE sessions
                    SET llm_messages = NULL, updated_at = %s
                    WHERE id = %s
                    """,
                    (datetime.now(timezone.utc), session_id),
                )

    def get_user_id(self, session_id: str):
        """Return the session's user_id, or None if unknown."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT user_id FROM sessions WHERE id = %s", (session_id,))
                row = cur.fetchone()
        return row["user_id"] if row else None

    def list_sessions(self, user_id: str) -> list:
        """Return one row per session for a user, newest first.

        Each row carries a `title` derived from the first user-role message (or
        None for an empty session), plus message_count. Uses the
        sessions_user_id_updated_at_idx index for the ORDER BY.
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, created_at, updated_at, messages,
                           jsonb_array_length(messages) AS message_count
                    FROM sessions
                    WHERE user_id = %s
                    ORDER BY created_at DESC
                    """,
                    (user_id,),
                )
                rows = cur.fetchall()
        out = []
        for row in rows:
            title = None
            for m in row["messages"] or []:
                if isinstance(m, dict) and m.get("role") == "user":
                    title = (m.get("content") or "").strip() or None
                    break
            out.append({
                "session_id": str(row["id"]),
                "title": title,
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "message_count": row["message_count"],
            })
        return out

    def count_sessions(self, user_id: str) -> int:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS n FROM sessions WHERE user_id = %s",
                    (user_id,),
                )
                row = cur.fetchone()
        return int(row["n"]) if row else 0

    def delete_session(self, session_id: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM sessions WHERE id = %s", (session_id,))

    def delete_oldest_sessions(self, user_id: str, limit: int) -> list:
        """Delete the oldest sessions for this user. Returns deleted ids."""
        if limit <= 0:
            return []
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    WITH doomed AS (
                        SELECT id FROM sessions
                        WHERE user_id = %s
                        ORDER BY created_at ASC
                        LIMIT %s
                    )
                    DELETE FROM sessions
                    WHERE id IN (SELECT id FROM doomed)
                    RETURNING id
                    """,
                    (user_id, limit),
                )
                rows = cur.fetchall()
        return [str(row["id"]) for row in rows]

    def delete_sessions_for_user(self, user_id: str) -> list:
        """Delete every session owned by this user. Returns deleted ids."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM sessions WHERE user_id = %s RETURNING id",
                    (user_id,),
                )
                rows = cur.fetchall()
        return [str(row["id"]) for row in rows]

    def get_or_create_user(self, email: str) -> dict:
        """Insert a users row for this email, or return the existing one."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users (email) VALUES (%s)
                    ON CONFLICT (email) DO UPDATE SET email = EXCLUDED.email
                    RETURNING id, email
                    """,
                    (email,),
                )
                row = cur.fetchone()
        return {"id": str(row["id"]), "email": row["email"]}

    def get_user(self, user_id: str):
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, email FROM users WHERE id = %s",
                    (user_id,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return {"id": str(row["id"]), "email": row["email"]}
