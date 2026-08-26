"""StorageService — the single gateway between the HTTP API / (future) Agent
Runtime and the three storage layers.

    Frontend → HTTP API → StorageService → Redis / PostgreSQL / pgvector

Nothing outside StorageService may touch Redis/PostgreSQL directly, so a future
Agent Runtime can reuse it unchanged:

    # TODO(Future Agent Runtime): call StorageService here, instead of touching
    # Redis/PostgreSQL directly.
"""
import uuid

from .cache import CacheLayer
from .config import CACHE_RECENT_MESSAGES, DEFAULT_USER_ID
from .embeddings import generate_embedding
from .persistence import PersistenceLayer
from .semantic import SemanticLayer


class StorageService:
    """Unified entry point for all storage operations."""

    RECENT_MESSAGES = CACHE_RECENT_MESSAGES  # Redis cache window (最近 N 条)

    def __init__(self, cache=None, persistence=None, semantic=None):
        self.cache = cache or CacheLayer()
        self.persistence = persistence or PersistenceLayer()
        self.semantic = semantic or SemanticLayer()

    # -- Cache ------------------------------------------------------------

    def get_session(self, session_id: str) -> list:
        """Return session messages. Fast path: Redis cache; fall back to PostgreSQL.

        Because Redis only holds the recent window, a cold cache returns the full
        history from PostgreSQL and re-seeds Redis with the recent window.
        """
        cached = self.cache.get_session(session_id)
        if cached is not None:
            return cached
        history = self.persistence.get_history(session_id)
        if history is not None:
            self.cache.set_session(session_id, history[-self.RECENT_MESSAGES:])
            return history
        return []

    def update_session(self, session_id: str, message: dict) -> list:
        """Append a single message to the Redis cache window."""
        return self.cache.update_session(session_id, message)

    # -- Persistence ------------------------------------------------------

    def save_session(self, session_id: str, user_id: str, messages: list) -> None:
        """Upsert the full session history into PostgreSQL."""
        self.persistence.save_session(session_id, user_id, messages)

    def get_history(self, session_id: str):
        """Return the full session history from PostgreSQL (or None)."""
        return self.persistence.get_history(session_id)

    # -- Semantic ---------------------------------------------------------

    def store_memory(self, session_id: str, content: str, embedding: list) -> None:
        self.semantic.store_memory(session_id, content, embedding)

    def search_memory(self, query_embedding: list, limit: int = 5) -> list:
        return self.semantic.search_memory(query_embedding, limit)

    # -- Composite read ---------------------------------------------------

    def get_full_session(self, session_id: str) -> dict:
        """Session view for the GET API: messages + resolved user_id."""
        messages = self.get_session(session_id)
        user_id = self.persistence.get_user_id(session_id) or DEFAULT_USER_ID
        return {"session_id": session_id, "user_id": user_id, "messages": messages}

    # -- Session lifecycle ------------------------------------------------

    def create_session(self, user_id: str) -> dict:
        """Pre-create an empty session row so it appears in the sidebar list.

        The first POST /sessions/{id}/messages will reuse this row via upsert.
        """
        new_id = str(uuid.uuid4())
        self.persistence.save_session(new_id, user_id, [])
        return {"session_id": new_id, "user_id": user_id, "messages": []}

    def list_user_sessions(self, user_id: str) -> list:
        """Newest-first list of this user's sessions for the sidebar."""
        return self.persistence.list_sessions(user_id)

    # -- Core message flow -------------------------------------------------

    def handle_user_message(self, session_id: str, user_id: str, message: str) -> dict:
        """Run a user message through the full storage pipeline (spec section IX).

        Flow:
          1. Redis 读取 Session（热缓存）
          2. Redis 不存在 → PostgreSQL 获取历史 → 最近 N 条写入 Redis
          3. 追加用户消息
          4. 更新 Redis
          5. 更新 PostgreSQL
          6. 语义记忆 → generate_embedding() → 写入 pgvector
          7. 返回当前 Session 数据
        """
        # 1. Redis 快速路径
        cached = self.cache.get_session(session_id)

        # 2. Redis 未命中 → 从 PostgreSQL 恢复。写入必须以 PostgreSQL 全量历史为
        #    准（Redis 只存最近 N 条），否则热缓存窗口会截断更早的消息。
        history = self.persistence.get_history(session_id) or []
        if cached is None and history:
            self.cache.set_session(session_id, history[-self.RECENT_MESSAGES:])

        # 3. 追加用户消息
        messages = history + [{"role": "user", "content": message}]

        # 4. 更新 Redis（保持最近 N 条窗口）
        self.cache.set_session(session_id, messages[-self.RECENT_MESSAGES:])

        # 5. 更新 PostgreSQL（全量 upsert）
        self.persistence.save_session(session_id, user_id, messages)

        # 6. 语义记忆：内容 → embedding → pgvector（当前是 Mock，见 embeddings.py）
        try:
            embedding = generate_embedding(message)
            if embedding:
                self.semantic.store_memory(session_id, message, embedding)
        except Exception as exc:
            # 语义层失败不应阻塞主消息流
            print(f"[storage] semantic memory skipped for session {session_id}: {exc}")

        # ------------------------------------------------------------------
        # TODO(Future Agent Runtime / LLM):
        #     user_message → [Agent Runtime] → assistant_message
        # 未来 Agent 在这里生成 assistant_message，再追加到 messages 并调用
        # StorageService 落库。当前阶段仅使用 Mock 回复测试完整链路，不是 Agent。
        # ------------------------------------------------------------------
        assistant = {
            "role": "assistant",
            "content": f"[MOCK] Received: {message}",
            "mock": True,
        }
        messages = messages + [assistant]

        self.cache.set_session(session_id, messages[-self.RECENT_MESSAGES:])
        self.persistence.save_session(session_id, user_id, messages)

        # 7. 返回当前 Session 数据（最近 N 条；完整历史可通过 GET 全量获取）
        return {
            "session_id": session_id,
            "user_id": user_id,
            "messages": messages[-self.RECENT_MESSAGES:],
        }
