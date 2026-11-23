"""Voice -> plan -> Grasshopper canvas, against the fake bridge."""

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from fake_bridge import FakeBridge
from fakes import rhinocommon as rc
from rhino_ai_mods.bridge_client import BridgeClient
from rhino_ai_mods.gh.builder import Builder
from rhino_ai_mods.gh.planner import Planner, parse_plan
from rhino_ai_mods.gh.recipes import voronoi_facade
from rhino_ai_mods.voice.pipeline import VoicePipeline, is_grasshopper_request
from rhino_ai_mods.voice.server import make_handler

LOUVRE_REPLY = """Here you go.
```json
{"title": "Louvres", "summary": "Vertical fins along a curve.",
 "inputs": [{"name": "base", "type": "geometry", "source": "selection"},
            {"name": "count", "type": "integer", "min": 2, "max": 100, "value": 20},
            {"name": "depth", "type": "number", "min": 0.05, "max": 1, "value": 0.3}],
 "outputs": ["fins"]}
```
```python
import Rhino.Geometry as rg
fins = []
```
"""


class StubLLM:
    name = "stub"

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def complete(self, messages, max_tokens=96):
        self.prompts.append(messages)
        return self.replies.pop(0) if self.replies else ""


@pytest.fixture
def bridge():
    b = FakeBridge()
    yield b
    b.close()


def make(bridge, replies=None, confirm=True):
    planner = Planner(StubLLM(replies) if replies is not None else None)
    builder = Builder(BridgeClient(port=bridge.port), planner, confirm=confirm)
    return VoicePipeline(bridge=BridgeClient(port=bridge.port), planner=planner, builder=builder)


@pytest.mark.parametrize("text,expected", [
    ("Build me a voronoi script that attaches to a facade.", True),
    ("build a stepping condition that steps back every 3 floors", True),
    ("make a grasshopper definition for louvres", True),
    ("in grasshopper, divide this curve into 20 points", True),
    ("sel prev", False),
    ("boolean union", False),
    ("make a box ten by ten", False),
])
def test_grasshopper_routing(text, expected):
    assert is_grasshopper_request(text) is expected


def test_recipe_build_without_model(bridge):
    out = make(bridge).handle("build me a voronoi script that attaches to a facade", "rhino")
    assert out.status == "built", out
    b = out.build
    assert b["title"] == "Voronoi facade" and not b["errors"]
    # confirm dialog shown before anything was added
    cmds = bridge.cmds()
    assert cmds.index("confirm") < cmds.index("gh_add_geometry_input")
    # 1 geometry + 3 sliders wired into the script by name, all grouped
    script = next(o for o in bridge.objects.values() if o["kind"] == "Python3Component")
    assert script["inputs"] == ["facade", "count", "seed", "frame"]
    assert sorted(w[2] for w in bridge.wires) == sorted(script["inputs"])
    group = next(o for o in bridge.objects.values() if o["kind"] == "GH_Group")
    assert len(group["members"]) == 5


def test_sliders_get_ranges_and_types(bridge):
    make(bridge).handle("stepped massing with 20 floors", "grasshopper")
    sliders = {o["nickname"]: o["args"] for o in bridge.objects.values() if o["kind"] == "slider"}
    assert sliders["floors"]["integer"] and sliders["floors"]["value"] == 20
    assert not sliders["floor_height"]["integer"]
    assert sliders["setback"]["min"] == 0


def test_cancel_in_dialog_builds_nothing(bridge):
    bridge.confirm_answer = False
    out = make(bridge).handle("build a voronoi facade", "grasshopper")
    assert out.status == "cancelled"
    assert not bridge.objects


def test_no_selection_still_builds_but_warns(bridge):
    bridge.selection = 0
    out = make(bridge).handle("build a voronoi facade", "grasshopper")
    assert out.status == "built"
    assert any("empty" in w for w in out.build["warnings"])


def test_model_plan_is_built(bridge):
    out = make(bridge, [LOUVRE_REPLY]).handle("build louvres along this curve", "grasshopper")
    assert out.status == "built" and out.build["title"] == "Louvres"
    script = next(o for o in bridge.objects.values() if o["kind"] == "Python3Component")
    assert script["inputs"] == ["base", "count", "depth"] and script["outputs"] == ["fins"]


def test_model_gets_recipe_as_starting_point(bridge):
    llm_reply = LOUVRE_REPLY.replace("Louvres", "Voronoi v2")
    p = make(bridge, [llm_reply])
    p.handle("build a voronoi facade with bigger openings near the top", "grasshopper")
    prompt = p.planner.backend.prompts[0][1]["content"]
    assert "tested recipe" in prompt and "voronoi_cells" in prompt


def test_repair_loop_fixes_errors(bridge):
    bridge.script_errors = [["NameError: name 'fins' is not defined"], []]
    fixed = "```python\nfins = []\n```"
    out = make(bridge, [LOUVRE_REPLY, fixed]).handle("build louvres", "grasshopper")
    assert out.status == "built" and out.build["repairs"] == 1
    assert "gh_update_script" in bridge.cmds()


def test_repair_gives_up_after_two_tries(bridge):
    bridge.script_errors = [["boom"], ["boom"], ["boom"]]
    bad = "```python\nraise Exception\n```"
    out = make(bridge, [LOUVRE_REPLY, bad, bad]).handle("build louvres", "grasshopper")
    assert out.status == "built_with_errors" and out.build["repairs"] == 2


def test_garbage_model_reply_falls_back_to_recipe(bridge):
    out = make(bridge, ["sorry, I can't"]).handle("build a voronoi facade", "grasshopper")
    assert out.status == "built" and out.build["title"] == "Voronoi facade"
    assert out.build["notes"]


def test_no_model_no_recipe_is_a_clear_error(bridge):
    out = make(bridge).handle("build a kangaroo form-finding mesh", "grasshopper")
    assert out.status == "error" and "--gh-llm" in out.detail


def test_parse_plan_variants():
    assert parse_plan(LOUVRE_REPLY).title == "Louvres"
    assert parse_plan("no blocks") is None
    assert parse_plan("```json\n{bad json}\n```\n```python\nx=1\n```") is None


def test_model_plan_code_runs_in_simulated_rhino():
    """A plan the model returns for a recipe request must still execute."""
    rc.install()
    try:
        env, msgs = rc.run_script(voronoi_facade("").code, facade=[rc.vertical_facade(8, 4)],
                                  count=10, seed=0, frame=0.1)
        assert len(env["cells"]) == 10 and not msgs
    finally:
        rc.uninstall()


def test_http_grasshopper_mode_is_async(bridge):
    p = make(bridge)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(p))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{httpd.server_address[1]}/dictation",
            data=json.dumps({"text": "build a voronoi facade", "mode": "grasshopper",
                             "source": "hushtype"}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            assert r.status == 202
        for _ in range(100):
            if any(o["kind"] == "GH_Group" for o in bridge.objects.values()):
                break
            threading.Event().wait(0.05)
        assert any(o["kind"] == "GH_Group" for o in bridge.objects.values())
    finally:
        httpd.shutdown()
