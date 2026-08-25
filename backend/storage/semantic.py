"""Semantic Layer — PostgreSQL + pgvector.

Stores per-message embeddings in `memory_vectors` for future cross-session
semantic retrieval by the Agent Runtime. Retrieval uses cosine distance and the
IVFFlat index (`embedding vector_cosine_ops`, see backend/schema.sql).
"""
from datetime import datetime, timezone

import psycopg

from .config import DATABASE_URL

# Number of IVFFlat lists to probe on similarity search (default is 1, which can
# miss everything on small demo tables). Must be <= lists in the index (100).
IVFFLAT_PROBES = 100


def _vector_literal(vector: list) -> str:
    """pgvector accepts a string like "[0.1,0.2,...]" for a VECTOR column."""
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


class SemanticLayer:
    """Read/write for the `memory_vectors` table."""

    def __init__(self, conninfo: str = DATABASE_URL):
        self.conninfo = conninfo

    def _connect(self):
        return psycopg.connect(self.conninfo)

    def store_memory(self, session_id: str, content: str, embedding: list) -> None:
        """Insert one memory row with its vector embedding."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO memory_vectors (id, session_id, content, embedding, created_at)
                    VALUES (gen_random_uuid(), %s, %s, %s::vector, %s)
                    """,
                    (
                        session_id,
                        content,
                        _vector_literal(embedding),
                        datetime.now(timezone.utc),
                    ),
                )

    def search_memory(self, query_embedding: list, limit: int = 5) -> list:
        """Return the `limit` closest memories by cosine distance (<=>)."""
        q = _vector_literal(query_embedding)
        with self._connect() as conn:
            with conn.cursor() as cur:
                # IVFFlat only scans `ivfflat.probes` lists (default 1). On small
                # demo tables that can return nothing, so scan all lists — the
                # IVFFlat index is still used. Tune for production scale.
                cur.execute(f"SET ivfflat.probes = {IVFFLAT_PROBES}")
                cur.execute(
                    """
                    SELECT session_id, content, 1 - (embedding <=> %s::vector) AS similarity
                    FROM memory_vectors
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (q, q, limit),
                )
                rows = cur.fetchall()
        return [
            {"session_id": str(row[0]), "content": row[1], "similarity": float(row[2])}
            for row in rows
        ]
