"""Concurrent PostgreSQL load through the real PersistenceLayer.

N threads each run M `get_user_id` queries (the lookup every chat request does).
A side connection samples pg_stat_activity to record peak connections.

    docker compose up -d postgres
    cd backend && .venv/bin/python scripts/bench_db_pool.py [threads] [queries_per_thread]
"""
import sys
import threading
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from storage.config import DATABASE_URL  # noqa: E402
from storage.db import close_pool  # noqa: E402
from storage.persistence import PersistenceLayer  # noqa: E402

THREADS = int(sys.argv[1]) if len(sys.argv) > 1 else 50
QUERIES = int(sys.argv[2]) if len(sys.argv) > 2 else 20


def sample_connections(stop: threading.Event, peak: list):
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        while not stop.is_set():
            n = conn.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
            ).fetchone()[0]
            peak[0] = max(peak[0], n)
            time.sleep(0.02)


def worker(persistence: PersistenceLayer, errors: Counter):
    sid = str(uuid.uuid4())
    for _ in range(QUERIES):
        try:
            persistence.get_user_id(sid)
        except Exception as exc:
            errors[type(exc).__name__] += 1


def main():
    persistence = PersistenceLayer()
    persistence.get_user_id(str(uuid.uuid4()))  # warm-up

    stop, peak, errors = threading.Event(), [0], Counter()
    sampler = threading.Thread(target=sample_connections, args=(stop, peak))
    sampler.start()
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        for _ in range(THREADS):
            pool.submit(worker, persistence, errors)
    wall = time.perf_counter() - t0
    stop.set()
    sampler.join()
    close_pool()

    total = THREADS * QUERIES
    print(f"{THREADS} threads x {QUERIES} queries = {total}")
    print(f"  wall time        : {wall:.2f}s")
    print(f"  throughput       : {total / wall:.0f} q/s")
    print(f"  avg per query    : {wall / QUERIES * 1000:.1f} ms (per thread)")
    print(f"  peak PG conns    : {peak[0]}")
    print(f"  errors           : {dict(errors) or 0}")


if __name__ == "__main__":
    main()
