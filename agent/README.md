# Agent

未来 **Agent Runtime** 的归属目录。本阶段（三层存储架构）**不实现** Agent / LLM / 真实 Embedding，
这里只是一个占位，用于把「前端 → 后端 → Agent」三块职责在目录结构上先分开。

## 目标结构

```
Frontend (frontend/)
    ↓
Agent API (backend/api/routes.py  里的 TODO: Future Agent API)
    ↓
Agent Runtime (agent/)            ← 本目录未来放这里
    ↓
StorageService (backend/storage/)  ← Agent 唯一允许访问存储的入口
    ↓
Redis / PostgreSQL / pgvector
```

## 未来在这里放什么

- `agent/runtime.py`（或等价模块）—— Agent 核心循环：拼上下文 → 调 LLM → 处理 tool calls。
- `agent/prompts.py` —— system prompt / 提示词。
- `agent/llm/` —— 供应商抽象（OpenAI-compatible 等）。
- `agent/tools/` —— 工具注册表（服务端工具、客户端工具）。
- `agent/rag/` —— 从博文构建向量索引 + 检索。

## 接入约束（必须遵守）

Agent Runtime **只允许通过 `backend/storage/service.py` 的 `StorageService`** 访问存储，
不得直接触达 Redis / PostgreSQL / pgvector（对应代码里已用 `TODO` 标注）。

## 现有接入点（代码里已预留）

1. `backend/api/routes.py` —— `TODO(Future Agent API)`，未来 `POST /api/agent/chat` 的入口。
2. `backend/storage/service.py` —— `handle_user_message()` 内的
   `TODO(Future Agent Runtime / LLM)` 块，当前放的是 `[MOCK]` 回复，未来在这里调 Agent 生成
   `assistant_message` 后走 StorageService 落库。
3. `backend/storage/embeddings.py` —— 把 mock 的 `generate_embedding()` 换成真实 Embedding API
   （签名不变），语义检索即成为真实跨 Session 记忆。
