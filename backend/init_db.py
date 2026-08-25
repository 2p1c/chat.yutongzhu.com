"""Initialize the PostgreSQL database from backend/schema.sql (idempotent).

Usage (from backend/):
    python init_db.py

This is a fallback / manual re-init. On a fresh docker-compose volume the schema
is applied automatically via docker-entrypoint-initdb.d.
"""
from pathlib import Path

import psycopg

from storage.config import DATABASE_URL

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def init_db(conninfo: str = DATABASE_URL) -> None:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    with psycopg.connect(conninfo) as conn:
        with conn.cursor() as cur:
            cur.execute(schema)
    print("[init_db] schema applied successfully")


if __name__ == "__main__":
    init_db()
