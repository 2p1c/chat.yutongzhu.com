# { Yutong Zhu } — Chat Storage Service

Three-layer session storage for a future Agent. This phase implements **only the
storage architecture** — no Agent, no LLM, no real Embedding API. The existing
static frontend (`frontend/`) is wired to a real storage backend so messages
actually persist and survive page refreshes.

```
Frontend input
    ↓
HTTP API  (FastAPI, backend/)
    ↓
StorageService  (unified gateway — the only thing that touches storage)
    ↓
┌─────────────────────────────────────────────┐
│  ① Cache Layer     Redis      session:{id} │
│  ② Persistence     PostgreSQL sessions     │
│  ③ Semantic Layer  PostgreSQL+pgvector     │
│                     memory_vectors          │
└─────────────────────────────────────────────┘
```

Future Agent Runtime will call `StorageService` the same way the API does today
(see the `TODO(Future Agent Runtime / LLM)` marker in
`backend/storage/service.py`). It never touches Redis/PostgreSQL directly.

## Architecture

| Layer | Tech | What it stores |
|---|---|---|
| ① Cache | Redis | Recent N messages of the active session, Hash key `session:{id}`, field `messages`, TTL 600s |
| ② Persistence | PostgreSQL | Full session history, `sessions` table, `messages JSONB` |
| ③ Semantic | PostgreSQL + pgvector | Per-message embeddings, `memory_vectors` table, `VECTOR(1536)`, IVFFlat cosine index |

Only two business tables exist: `sessions` and `memory_vectors` (`backend/schema.sql`).

## Layout

```
backend/
  main.py                  # FastAPI app: /api routes + serves frontend/
  schema.sql               # DDL (sessions, memory_vectors, IVFFlat index)
  init_db.py               # idempotent schema apply (fallback / re-init)
  requirements.txt
  .env.example
  api/routes.py            # POST/GET /api/sessions/{id}(/messages), /api/health
  storage/
    cache.py               # Redis CacheLayer
    persistence.py         # Postgres PersistenceLayer (sessions)
    semantic.py            # pgvector SemanticLayer (memory_vectors)
    embeddings.py          # generate_embedding() — MOCK, replace later
    service.py             # StorageService + handle_user_message
frontend/                  # static frontend (HTML/CSS/JS + vendor), wired to the API
agent/                     # future Agent Runtime (placeholder — not implemented yet)
docker-compose.yml         # Redis + pgvector/pg16
```

## Start

```bash
# 1. Databases (Redis + PostgreSQL/pgvector)
docker compose up -d

# 2. Backend (Python 3.11+; venv optional but recommended)
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python init_db.py          # applies backend/schema.sql (also auto-applied on fresh volume)
uvicorn main:app --port 8000

# 3. Open
open http://127.0.0.1:8000/
```

The backend serves both the API (`/api/...`) and the static frontend at `/`,
so the browser talks to one origin.

## Test

- **API:** `POST /api/sessions/{uuid}/messages` with `{"message":"你好"}`;
  `GET /api/sessions/{uuid}` to fetch the session.
- **Cache (Redis):** `docker exec chat-redis redis-cli HGETALL "session:{uuid}"`
- **Persistence:** `docker exec chat-postgres psql -U postgres -d chatdb -c "SELECT * FROM sessions"`
- **Semantic search:**
  ```python
  from storage.semantic import SemanticLayer
  from storage.embeddings import generate_embedding
  SemanticLayer().search_memory(generate_embedding("your query"))
  ```
- **Frontend:** type a message → a clearly-marked **Mock** assistant reply appears
  → refresh the page → the same session history is restored (session id lives in
  `localStorage["session_id"]`).

## Where the future Agent connects

1. The API is the seam: `Frontend → StorageService` today becomes
   `Frontend → Agent API → Agent Runtime → StorageService`.
2. In `backend/storage/service.py`, `handle_user_message` has a
   `TODO(Future Agent Runtime / LLM)` block where the assistant message will be
   generated instead of the current Mock reply.
3. In `backend/storage/embeddings.py`, replace the mock `generate_embedding`
   with a real Embedding API call (same signature). Semantic search then becomes
   real cross-session memory retrieval.
4. `backend/api/routes.py` has a `TODO(Future Agent API)` note for
   `POST /api/agent/chat`.
