"""Concurrency benchmark for the SSE chat endpoint. No Redis/PG/Agent needed.

A fake StorageService simulates a slow LLM (blocking sleep between tokens, like
`requests.iter_lines()` waiting on the Agent). We open N streams at once and
probe /api/health while they run.

    cd backend && .venv/bin/python scripts/bench_sse_concurrency.py [streams]
"""
import sys
import threading
import time
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from auth.deps import get_current_user  # noqa: E402
from main import create_app  # noqa: E402

STREAMS = int(sys.argv[1]) if len(sys.argv) > 1 else 10
TOKENS_PER_STREAM = 10
TOKEN_INTERVAL = 0.1  # seconds → each stream ideally takes ~1s
PORT = 8799
BASE = f"http://127.0.0.1:{PORT}"


class FakeStorage:
    def session_owned_by(self, session_id, user_id):
        return True

    def try_begin_generation(self, session_id):
        return "token"

    def end_generation(self, session_id, token):
        pass

    def stream_user_message(self, session_id, user_id, message, message_id=None):
        for i in range(TOKENS_PER_STREAM):
            time.sleep(TOKEN_INTERVAL)
            yield {"type": "delta", "delta": f"t{i} "}
        yield {"type": "done", "message": {"role": "assistant", "content": "ok"}}


def start_server():
    app = create_app()
    app.state.storage = FakeStorage()
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "bench"}
    server = uvicorn.Server(uvicorn.Config(app, port=PORT, log_level="warning"))
    thread = threading.Thread(target=server.run)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    return server, thread


def one_stream(_):
    req = urllib.request.Request(
        f"{BASE}/api/sessions/{uuid.uuid4()}/messages",
        data=b'{"message": "hi"}',
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=120) as r:
        r.read()
    return time.perf_counter() - t0


def probe_health(samples=5):
    out = []
    for _ in range(samples):
        t0 = time.perf_counter()
        urllib.request.urlopen(f"{BASE}/api/health", timeout=120).read()
        out.append((time.perf_counter() - t0) * 1000)
        time.sleep(0.1)
    return out


def main():
    server, thread = start_server()
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=STREAMS + 1) as pool:
        streams = [pool.submit(one_stream, i) for i in range(STREAMS)]
        time.sleep(0.2)
        health = pool.submit(probe_health).result()
        durations = [f.result() for f in streams]
    wall = time.perf_counter() - t0
    server.should_exit = True
    thread.join()

    ideal = TOKENS_PER_STREAM * TOKEN_INTERVAL
    print(f"{STREAMS} concurrent streams, ideal ~{ideal:.1f}s each")
    print(f"  wall time        : {wall:.2f}s")
    print(f"  per-stream (max) : {max(durations):.2f}s")
    print(f"  /api/health ms   : {', '.join(f'{x:.0f}' for x in health)}")


if __name__ == "__main__":
    main()
