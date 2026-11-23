"""Dictation app's view: POST /dictation -> rhino-voice (subprocess) -> real bridge script -> fake Rhino."""

import importlib.util
import json
import os
import pathlib
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

from fakes import dotnet

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge" / "rhino_ai_bridge.py"


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def stack(tmp_path):
    env = dotnet.install(commands=("Box", "SelPrev", "Loft", "BooleanUnion", "Delete"))
    spec = importlib.util.spec_from_file_location("bridge_for_voice", BRIDGE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    bridge = mod.Bridge(port=0)
    bridge.start()
    aliases = tmp_path / "aliases.json"
    aliases.write_text(json.dumps({"section cut": "_ClippingPlane"}))
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "rhino_ai_mods.voice.server", "--llm", "none", "--gh-llm", "none",
         "--aliases", str(aliases), "serve", "--port", str(port)],
        env={**os.environ, "RHINO_AI_BRIDGE_PORT": str(bridge.sock.getsockname()[1])},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for _ in range(100):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
            break
        except OSError:
            time.sleep(0.05)
    env.url = f"http://127.0.0.1:{port}/dictation"
    yield env
    proc.terminate()
    proc.wait(5)
    bridge.stop()
    dotnet.uninstall()


def post(url, text, mode):
    req = urllib.request.Request(url, data=json.dumps(
        {"text": text, "app": "Rhino.exe", "source": "hushtype", "mode": mode}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def wait_for(pred, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False


def test_spoken_commands_reach_the_command_line_unconfirmed(stack):
    assert post(stack.url, "Select previous.", "rhino")[0] == 200
    assert post(stack.url, "SelPrev", "dictate")[0] == 200
    assert post(stack.url, "section cut", "rhino")[0] == 200       # user alias
    assert post(stack.url, "delete", "rhino")[0] == 200
    assert stack.app.keystrokes == [("_SelPrev", False), ("_SelPrev", False),
                                    ("_ClippingPlane", False), ("_Delete", False)]


def test_prose_while_rhino_focused_gets_pasted(stack):
    code, body = post(stack.url, "Note for the review: the north facade needs work.", "dictate")
    assert code == 409 and body["status"] == "not_a_command"
    assert stack.app.keystrokes == []


def test_voice_grasshopper_build_with_confirm_dialog(stack):
    stack.rhino.selected.append(stack.rhino.make_object("Brep", "facade"))
    code, _ = post(stack.url, "Build me a voronoi script that attaches to the facade with 80 cells.",
                   "grasshopper")
    assert code == 202
    assert wait_for(lambda: any(type(o).__name__ == "Group" for o in stack.gh.doc.Objects))
    title, message = stack.app.dialogs[0]
    assert "Voronoi facade" in title and "1 object(s) selected" in message and "80" in message
    sliders = {o.NickName: o.value for o in stack.gh.doc.Objects if type(o).__name__ == "Slider"}
    assert sliders["count"] == 80
    assert any("[kazi] built 'Voronoi facade'" in line for line in stack.app.lines)


def test_voice_grasshopper_cancel(stack):
    stack.app.dialog_answer = False
    assert post(stack.url, "build a stepped massing", "grasshopper")[0] == 202
    assert wait_for(lambda: any("cancelled" in line for line in stack.app.lines))
    assert stack.gh.doc.Objects == []


def test_build_phrase_on_rhino_hotkey_routes_to_grasshopper(stack):
    assert post(stack.url, "build a terraced massing with 9 floors", "rhino")[0] == 202
    assert wait_for(lambda: any(type(o).__name__ == "Group" for o in stack.gh.doc.Objects))
