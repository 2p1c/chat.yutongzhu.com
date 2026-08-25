-- Three-layer storage schema (Persistence + Semantic layers).
-- The Cache Layer (Redis) needs no DDL.
--
-- This file is idempotent: it can run on every boot via
--     docker-entrypoint-initdb.d/01_schema.sql  (fresh volume)
-- or manually via
--     python init_db.py
--
-- Only two business tables are allowed (spec section 10): sessions, memory_vectors.

CREATE EXTENSION IF NOT EXISTS vector;

-- ① Persistence Layer — full session history (messages as JSONB)
CREATE TABLE IF NOT EXISTS sessions (
    id         UUID PRIMARY KEY,
    user_id    TEXT NOT NULL,
    messages   JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ② Semantic Layer — embedding vectors for cross-session memory retrieval
CREATE TABLE IF NOT EXISTS memory_vectors (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    content    TEXT NOT NULL,
    embedding  VECTOR(1536),
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- IVFFlat index for cosine-similarity search (spec: vector_cosine_ops)
CREATE INDEX IF NOT EXISTS memory_vectors_embedding_idx
    ON memory_vectors
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
