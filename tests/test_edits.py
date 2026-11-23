"""Voice edits to the last build: sliders, toggles, undo, bake, remove, model code edits."""

import pytest

from fake_bridge import FakeBridge
from rhino_ai_mods.bridge_client import BridgeClient
from rhino_ai_mods.gh.builder import Builder
from rhino_ai_mods.gh.edits import Editor
from rhino_ai_mods.gh.planner import Planner
from rhino_ai_mods.gh.recipes import RECIPES
from rhino_ai_mods.voice.pipeline import VoicePipeline, is_new_build


class StubLLM:
    name = "stub"

    def __init__(self, replies):
        self.replies, self.prompts = list(replies), []

    def complete(self, messages, max_tokens=96):
        self.prompts.append(messages[-1]["content"])
        return self.replies.pop(0)


@pytest.fixture
def bridge():
    b = FakeBridge()
    yield b
    b.close()


def setup(bridge, recipe, request="", llm=None):
    client = BridgeClient(port=bridge.port)
    planner = Planner(llm)
    Builder(client, None, confirm=False).build(RECIPES[recipe][0](request))
    editor = Editor(client, planner, confirm=True)
    pipe = VoicePipeline(bridge=client, planner=planner, editor=editor,
                         builder=Builder(client, None, confirm=False))
    return pipe, editor


def value(bridge, name, kind="sliders"):
    guid = bridge.builds[-1][kind][name]
    o = bridge.objects[guid]
    return o.get("value", o["args"].get("value"))


@pytest.mark.parametrize("recipe,speech,name,expected", [
    ("voronoi_facade", "more cells", "count", 75),
    ("voronoi_facade", "a lot more cells", "count", 96),
    ("voronoi_facade", "fewer cells", "count", 48),
    ("voronoi_facade", "make the frame thinner", "frame", 0.12),
    ("voronoi_facade", "thicker frame please", "frame", 0.1875),
    ("voronoi_facade", "bigger openings", "frame", 0.12),
    ("voronoi_facade", "120 cells", "count", 120),
    ("voronoi_facade", "new layout", "seed", 2),
    ("voronoi_facade", "set the count to 30", "count", 30),
    ("stepped_massing", "set floors to 20", "floors", 20),
    ("stepped_massing", "make it 30 floors", "floors", 30),
    ("stepped_massing", "make the building taller", "floors", 15),
    ("stepped_massing", "bigger setback", "setback", 2.5),
    ("stepped_massing", "increase the floor height a bit", "floor_height", 3.85),
    ("stepped_massing", "set the floor height to 4.2", "floor_height", 4.2),
    ("fins", "deeper fins", "depth", 0.75),
    ("fins", "more fins", "count", 25),
    ("fins", "rotate the fins more", "rotation", 15),
    ("fins", "rotate them 30 degrees", "rotation", 30),
    ("fins", "more twist", "twist_range", 9),   # 0 -> 10% of the range
    ("panels", "bigger panels", "columns", 8),
    ("panels", "wider joints", "gap", 0.025),
    ("attractor_openings", "move the attractor up", "attractor_y", 0.75),
    ("attractor_openings", "move the attractor to the left", "attractor_x", 0.15),
    ("attractor_openings", "bigger openings", "max_size", 1.0625),
    ("diagrid", "thicker members", "radius", 0.1875),
    ("diagrid", "more bays", "bays", 10),
])
def test_slider_edits(bridge, recipe, speech, name, expected):
    pipe, _ = setup(bridge, recipe)
    out = pipe.handle(speech, "grasshopper")
    assert out.status == "edited", out
    assert value(bridge, name) == pytest.approx(expected)
    assert any("[kazi]" not in m and name in m for m in bridge.messages) or out.detail


def test_integer_never_gets_stuck(bridge):
    pipe, _ = setup(bridge, "diagrid", "2 bays")
    for _ in range(3):
        pipe.handle("fewer bays", "grasshopper")
    assert value(bridge, "bays") == 1   # stops at the slider min, doesn't go to 0
    pipe.handle("more bays", "grasshopper")
    assert value(bridge, "bays") == 2


def test_toggles_flip_and_set(bridge):
    pipe, _ = setup(bridge, "fins")
    assert pipe.handle("flip the fins", "grasshopper").status == "edited"
    assert value(bridge, "flip", "toggles") is True
    pipe.handle("make them horizontal", "grasshopper")
    assert value(bridge, "horizontal", "toggles") is True
    pipe2, _ = setup(bridge, "panels")
    pipe2.handle("brick bond", "grasshopper")
    assert value(bridge, "stagger", "toggles") is True
    pipe2.handle("no stagger", "grasshopper")
    assert value(bridge, "stagger", "toggles") is False


def test_undo_reverts_the_last_edit_only(bridge):
    pipe, _ = setup(bridge, "voronoi_facade")
    pipe.handle("more cells", "grasshopper")
    pipe.handle("thinner frame", "grasshopper")
    assert pipe.handle("undo", "grasshopper").status == "undone"
    assert value(bridge, "frame") == pytest.approx(0.15) and value(bridge, "count") == 75
    pipe.handle("undo that", "grasshopper")
    assert value(bridge, "count") == 60


def test_multi_slider_edit_and_undo(bridge):
    pipe, _ = setup(bridge, "panels")   # 10 x 8
    out = pipe.handle("more panels", "grasshopper")
    assert len(out.build["changes"]) == 2
    assert (value(bridge, "columns"), value(bridge, "rows")) == (12, 10)
    pipe.handle("undo", "grasshopper")
    assert (value(bridge, "columns"), value(bridge, "rows")) == (10, 8)


def test_new_build_is_not_an_edit(bridge):
    pipe, _ = setup(bridge, "voronoi_facade")
    out = pipe.handle("build a stepped massing with 10 floors", "grasshopper")
    assert out.status == "built" and len(bridge.builds) == 2
    assert is_new_build("make me a diagrid") and is_new_build("add some fins to the facade")
    assert not is_new_build("make the frame thinner") and not is_new_build("more cells")


def test_bake_and_remove_by_voice(bridge):
    pipe, _ = setup(bridge, "voronoi_facade")
    assert pipe.handle("bake it", "grasshopper").status == "baked"
    bridge.confirm_answer = False
    assert pipe.handle("delete that build", "grasshopper").status == "cancelled"
    assert len(bridge.builds) == 1
    bridge.confirm_answer = True
    assert pipe.handle("remove the build", "grasshopper").status == "removed"
    assert bridge.builds == []


def test_nothing_built_yet_falls_through_to_build(bridge):
    client = BridgeClient(port=bridge.port)
    planner = Planner(None)
    pipe = VoicePipeline(bridge=client, planner=planner, editor=Editor(client),
                         builder=Builder(client, None, confirm=False))
    out = pipe.handle("voronoi with more cells", "grasshopper")
    assert out.status == "built"


def test_unknown_edit_without_model_is_not_an_edit(bridge):
    _, editor = setup(bridge, "voronoi_facade")
    assert editor.handle("make the openings circular").status == "not_an_edit"


def test_model_code_edit_confirm_apply_and_undo(bridge):
    new = "```python\ncells, openings, sites = [], [], []  # circular\n```"
    llm = StubLLM([new])
    pipe, editor = setup(bridge, "voronoi_facade", llm=llm)
    script = bridge.builds[-1]["script"]
    old = bridge.objects[script]["code"]
    out = pipe.handle("make the openings circular", "grasshopper")
    assert out.status == "edited", out
    assert "circular" in bridge.objects[script]["code"]
    assert "Keep exactly the same input names (facade, count, seed, frame)" in llm.prompts[0]
    pipe.handle("undo", "grasshopper")
    assert bridge.objects[script]["code"] == old


def test_model_code_edit_reverts_on_error(bridge):
    llm = StubLLM(["```python\nboom(\n```"])
    pipe, _ = setup(bridge, "voronoi_facade", llm=llm)
    script = bridge.builds[-1]["script"]
    old = bridge.objects[script]["code"]
    bridge.script_errors = [[], ["SyntaxError: boom"]]
    out = pipe.handle("make the openings circular", "grasshopper")
    assert out.status == "error" and "reverted" in out.detail
    assert bridge.objects[script]["code"] == old


def test_model_code_edit_cancelled(bridge):
    pipe, _ = setup(bridge, "voronoi_facade", llm=StubLLM(["```python\nx = 1\n```"]))
    bridge.confirm_answer = False
    script = bridge.builds[-1]["script"]
    old = bridge.objects[script]["code"]
    assert pipe.handle("make the openings circular", "grasshopper").status == "cancelled"
    assert bridge.objects[script]["code"] == old


def test_code_edit_skipped_when_build_has_no_script(bridge):
    llm = StubLLM(["```python\nx = 1\n```"])
    pipe, editor = setup(bridge, "voronoi_facade", llm=llm)
    script = bridge.builds[-1]["script"]
    bridge.objects[script]["code"] = None          # like a plugin component (LunchBox etc.)
    out = editor.handle("make the openings circular")
    assert out.status == "not_an_edit" and "no script" in out.detail
    assert llm.prompts == []
