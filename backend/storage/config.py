"""Runtime configuration.

Read from environment variables, with an optional backend/.env file loaded via
python-dotenv (best-effort). Defaults target the local docker-compose setup.
"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass  # python-dotenv optional; env vars or defaults are enough

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/chatdb"
)
# Agent container HTTP endpoint (host port when Agent runs in docker on this host).
AGENT_URL = os.getenv("AGENT_URL", "http://localhost:8765")

# Size of the Redis cache window (spec: 最近 10 条消息).
CACHE_RECENT_MESSAGES = int(os.getenv("CACHE_RECENT_MESSAGES", "10"))

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_FROM = os.getenv("RESEND_FROM", "yutongzhu <noreply@chat.yutongzhu.site>")
# Comma-separated emails. Empty string → any address may sign in.
AUTH_EMAIL_ALLOWLIST = os.getenv("AUTH_EMAIL_ALLOWLIST", "")
