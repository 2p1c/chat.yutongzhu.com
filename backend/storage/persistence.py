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
