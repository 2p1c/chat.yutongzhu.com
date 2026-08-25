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
