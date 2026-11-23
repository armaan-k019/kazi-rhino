"""Model backends build valid requests (Anthropic SDK against a local fake API server)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from rhino_ai_mods.voice.llm import make_backend

anthropic = pytest.importorskip("anthropic")


@pytest.fixture
def fake_api(monkeypatch):
    seen = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append({"path": self.path, "body": body, "beta": self.headers.get("anthropic-beta")})
            stop = "refusal" if "REFUSE" in json.dumps(body) else "end_turn"
            resp = {"id": "msg_1", "type": "message", "role": "assistant", "model": body["model"],
                    "content": [{"type": "text", "text": '{"macro": "_Box", "is_command": true}'}],
                    "stop_reason": stop, "stop_sequence": None,
                    "usage": {"input_tokens": 10, "output_tokens": 5}}
            data = json.dumps(resp).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("ANTHROPIC_BASE_URL", f"http://127.0.0.1:{srv.server_address[1]}")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    yield seen
    srv.shutdown()


def test_anthropic_backend_request(fake_api):
    b = make_backend("anthropic")
    out = b.complete([{"role": "system", "content": "sys"}, {"role": "user", "content": "make a box"}],
                     max_tokens=6000)
    assert "_Box" in out
    req = fake_api[0]
    assert req["body"]["model"] == "claude-opus-5-5"
    assert req["body"]["system"] == "sys"
    assert req["body"]["messages"] == [{"role": "user", "content": "make a box"}]
    assert req["body"]["fallbacks"] == "default"
    assert req["body"]["output_config"] == {"effort": "medium"}
    assert "server-side-fallback-2026-07-01" in req["beta"]


def test_anthropic_refusal_returns_empty(fake_api):
    b = make_backend("anthropic")
    assert b.complete([{"role": "user", "content": "REFUSE"}]) == ""
