"""Shared PostgreSQL connection pool for the persistence and semantic layers.

A new connection costs a TCP handshake + auth + a PG backend process, and PG
caps them (max_connections, default 100). The pool reuses a bounded set.
"""
import threading

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import DATABASE_URL, DB_POOL_MAX_SIZE

_pool: ConnectionPool | None = None
_lock = threading.Lock()


def get_pool() -> ConnectionPool:
    global _pool
    with _lock:
        if _pool is None:
            _pool = ConnectionPool(
                DATABASE_URL,
                min_size=2,
                max_size=DB_POOL_MAX_SIZE,
                kwargs={"row_factory": dict_row},
                # Drop connections killed while idle (e.g. PG restart) before handing them out.
                check=ConnectionPool.check_connection,
                timeout=10,
                open=True,
            )
    return _pool


def close_pool() -> None:
    global _pool
    with _lock:
        if _pool is not None:
            _pool.close()
            _pool = None
