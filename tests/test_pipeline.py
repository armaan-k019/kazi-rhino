import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from rhino_ai_mods.bridge_client import BridgeClient, BridgeError
from rhino_ai_mods.voice.llm import LLMMapper, parse_reply
from rhino_ai_mods.voice.pipeline import VoicePipeline
from rhino_ai_mods.voice.server import make_handler

from fake_bridge import FakeBridge


class StubBackend:
    name = "stub"

    def __init__(self, replies):
        self.replies = replies

    def complete(self, messages):
        return self.replies.get(messages[-1]["content"], '{"macro": "", "is_command": false}')


@pytest.fixture
def bridge():
    b = FakeBridge()
    yield b
    b.close()


def make_pipeline(bridge, replies=None, **kw):
    llm = LLMMapper(StubBackend(replies or {})) if replies is not None else None
    return VoicePipeline(bridge=BridgeClient(port=bridge.port), llm=llm, **kw)


def test_bridge_client_errors(bridge):
    c = BridgeClient(port=bridge.port)
    assert c.call("ping") == {"echo": {}}
    with pytest.raises(BridgeError, match="kaboom"):
        c.call("boom")


def test_bridge_unreachable():
    with pytest.raises(BridgeError, match="Can't reach"):
        BridgeClient(port=1).call("ping")


def test_rule_command_runs_with_enter(bridge):
    p = make_pipeline(bridge)
    out = p.handle("Boolean union.", "dictate")
    assert out.status == "ran"
    assert bridge.macros() == [("_BooleanUnion", True)]


def test_delete_waits_for_confirmation(bridge):
    out = make_pipeline(bridge).handle("delete", "rhino")
    assert out.status == "typed_for_confirm"
    assert bridge.macros() == [("_Delete", False)]


def test_model_maps_free_speech(bridge):
    p = make_pipeline(bridge, {"make a box ten by ten by five":
                               'Sure: {"macro": "_Box 0,0,0 10,10,0 5", "is_command": true}'})
    out = p.handle("make a box ten by ten by five", "rhino")
    assert (out.status, out.macro, out.source) == ("ran", "_Box 0,0,0 10,10,0 5", "llm")


def test_model_invented_command_is_rejected(bridge):
    p = make_pipeline(bridge, {"do magic": '{"macro": "_MakeMagic", "is_command": true}'})
    out = p.handle("do magic", "dictate")
    assert out.status == "not_a_command"


def test_dictate_mode_lets_prose_through(bridge):
    out = make_pipeline(bridge, {}).handle("note to self, check the stair", "dictate")
    assert out.status == "not_a_command"
    assert bridge.macros() == []


def test_rhino_mode_types_raw_text_without_enter(bridge):
    out = make_pipeline(bridge, {}).handle("sub d", "rhino")
    assert out.status == "typed_raw"
    assert bridge.macros() == [("SubD", False)]


def test_parse_reply_handles_garbage():
    assert not parse_reply("no json here").is_command
    assert not parse_reply('{"macro": "_Box"').is_command


def _post(port, body):
    req = urllib.request.Request(f"http://127.0.0.1:{port}/dictation", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_http_contract(bridge):
    p = make_pipeline(bridge, {"make a sphere": '{"macro": "_Sphere 0,0,0 1", "is_command": true}'})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(p))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    try:
        assert _post(port, {"text": "undo", "mode": "dictate", "source": "hushtype"})[0] == 200
        assert _post(port, {"text": "dear client, thanks", "mode": "dictate"})[0] == 409
        assert _post(port, {"text": "make a sphere", "mode": "rhino"})[0] == 202
    finally:
        httpd.shutdown()


def test_http_503_when_rhino_is_down():
    p = VoicePipeline(bridge=BridgeClient(port=1))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(p))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        assert _post(httpd.server_address[1], {"text": "undo", "mode": "dictate"})[0] == 503
    finally:
        httpd.shutdown()
