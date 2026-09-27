"""Stand-in for the Agent container: streams a slow SSE reply, no LLM calls.

Lets you load-test the real backend (Redis + PG + multi-worker) for free:

    .venv/bin/python scripts/fake_agent.py [port] [tokens]   # default :8766, 20 tokens (~2s)
    AGENT_URL=http://127.0.0.1:8766 .venv/bin/uvicorn main:app --port 8001 --workers 2
"""
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8766
TOKENS = int(sys.argv[2]) if len(sys.argv) > 2 else 20
TOKEN_INTERVAL = 0.1


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for i in range(TOKENS):
            time.sleep(TOKEN_INTERVAL)
            self._event({"delta": f"t{i} "})
        self._event({
            "done": True,
            "message": {"role": "assistant", "content": "fake reply"},
            "usage": {"prompt_tokens": 1, "completion_tokens": TOKENS},
        })
        self.wfile.write(b"data: [DONE]\n\n")

    def _event(self, payload):
        self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode())
        self.wfile.flush()

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
