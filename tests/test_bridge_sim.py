"""Run the real bridge script (bridge/rhino_ai_bridge.py) against fake Rhino/Grasshopper objects."""

import importlib.util
import pathlib

import pytest

from fakes import dotnet
from rhino_ai_mods.bridge_client import BridgeClient, BridgeError

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge" / "rhino_ai_bridge.py"


@pytest.fixture
def rhino(request):
    kwargs = getattr(request, "param", {})
    env = dotnet.install(**kwargs)
    spec = importlib.util.spec_from_file_location("rhino_ai_bridge_under_test", BRIDGE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    bridge = mod.Bridge(port=0)
    bridge.start()
    env.mod = mod
    env.client = BridgeClient(port=bridge.sock.getsockname()[1], timeout=10)
    yield env
    env.client.close()
    bridge.stop()
    dotnet.uninstall()


def objs(env, kind):
    return [o for o in env.gh.doc.Objects if type(o).__name__ == kind]


def test_ping(rhino):
    r = rhino.client.call("ping")
    assert r["bridge"] == rhino.mod.VERSION and r["document"] == "facade_study.3dm"
    assert r["grasshopper_open"] is True


def test_unknown_command_lists_known_ones(rhino):
    with pytest.raises(BridgeError, match="Known: .*gh_create_script"):
        rhino.client.call("nope")


def test_run_command_types_on_ui_thread(rhino):
    rhino.client.call("run_command", macro="_SelPrev", enter=False)
    rhino.client.call("run_command", macro="_Box", enter=True)
    assert rhino.app.keystrokes == [("_SelPrev", False), ("_Box", True)]


def test_run_command_cancels_a_running_command(rhino):
    rhino.app.in_command = True
    rhino.client.call("run_command", macro="_Loft")
    assert rhino.app.keystrokes == [("! _Loft", True)]


def test_run_command_script_mode_and_empty_macro(rhino):
    rhino.client.call("run_command", macro="_Zoom _All _Extents", mode="script")
    assert rhino.app.scripts == ["_Zoom _All _Extents"]
    with pytest.raises(BridgeError, match="macro is required"):
        rhino.client.call("run_command", macro="")
    rhino.client.call("run_command", macro="", allow_empty=True)  # = press Enter (repeat)
    assert rhino.app.keystrokes[-1] == ("", True)


def test_list_rhino_commands(rhino):
    assert rhino.client.call("list_rhino_commands")["commands"] == ["Box", "Loft", "SelPrev"]


def test_confirm_dialog(rhino):
    assert rhino.client.call("confirm", title="t", message="m")["ok"] is True
    rhino.app.dialog_answer = False
    assert rhino.client.call("confirm", title="t", message="m")["ok"] is False
    assert rhino.app.dialogs[0] == ("t", "m")


def test_selection_and_messages(rhino):
    rhino.rhino.selected.append(rhino.rhino.make_object("Brep", "north facade"))
    sel = rhino.client.call("get_selection")
    assert sel["count"] == 1 and sel["objects"][0]["layer"] == "Facade"
    rhino.client.call("rhino_message", text="hello")
    assert rhino.app.lines == ["[kazi] hello"]


def test_create_script_with_params_and_code(rhino):
    r = rhino.client.call("gh_create_script", code="a = x", nickname="wave",
                          inputs=[{"name": "pts", "access": "list"}, "amp", "freq"],
                          outputs=["curve", "pts_out"], x=300, y=50)
    comp = objs(rhino, "ScriptComponent")[0]
    assert comp.source == "a = x" and comp.NickName == "wave"
    assert [p.NickName for p in comp.Params.Input] == ["pts", "amp", "freq"]
    assert comp.Params.Input[0].Access == "list"
    # the standard-output "out" parameter is kept first
    assert [p.NickName for p in comp.Params.Output] == ["out", "curve", "pts_out"]
    assert comp.maintenance >= 1 and comp.Params.changed >= 1
    assert (comp.Attributes.Pivot.X, comp.Attributes.Pivot.Y) == (300.0, 50.0)
    assert r["setter"] == "SetSource" and r["success"] is True


@pytest.mark.parametrize("rhino", [{"script_with_out": False}], indirect=True)
def test_create_script_without_out_param(rhino):
    rhino.client.call("gh_create_script", code="", inputs=["a"], outputs=["b", "c"])
    comp = objs(rhino, "ScriptComponent")[0]
    assert [p.NickName for p in comp.Params.Input] == ["a"]
    assert [p.NickName for p in comp.Params.Output] == ["b", "c"]


def test_update_and_read_script_reports_errors(rhino):
    r = rhino.client.call("gh_create_script", code="x", nickname="s")
    comp = objs(rhino, "ScriptComponent")[0]
    comp.messages = [("Error", "NameError: y")]
    upd = rhino.client.call("gh_update_script", component="s", code="y = 1", inputs=["k"])
    assert upd["success"] is False and upd["errors"][0]["text"] == "NameError: y"
    assert [p.NickName for p in comp.Params.Input] == ["k"]
    read = rhino.client.call("gh_read_script", component=r["guid"])
    assert read["code"] == "y = 1"


def test_update_rejects_non_script(rhino):
    rhino.client.call("gh_add_component", name="Loft", nickname="L")
    with pytest.raises(BridgeError, match="not a script component"):
        rhino.client.call("gh_update_script", component="L", code="x")


def test_add_component_by_name_skips_obsolete(rhino):
    r = rhino.client.call("gh_add_component", name="loft")
    assert r["name"] == "Loft" and [i["nickname"] for i in r["inputs"]] == ["Curves", "Options"]
    with pytest.raises(BridgeError, match="No Grasshopper component"):
        rhino.client.call("gh_add_component", name="Banana")


def test_sliders_toggles_wiring_and_groups(rhino):
    rhino.client.call("gh_create_script", code="", nickname="s", inputs=["count", "flip"])
    sl = rhino.client.call("gh_add_slider", nickname="count", min=1, max=50, value=80, integer=True)
    tg = rhino.client.call("gh_add_toggle", nickname="flip", value=True)
    slider = objs(rhino, "Slider")[0]
    assert slider.value == 50 and slider.Slider.Type == "Integer" and slider.Slider.DecimalPlaces == 0
    assert objs(rhino, "Toggle")[0].Value is True
    rhino.client.call("gh_connect", source=sl["guid"], target="s", target_input="count")
    rhino.client.call("gh_connect", source="flip", target="s", target_input=1)
    comp = objs(rhino, "ScriptComponent")[0]
    assert [len(p.Sources) for p in comp.Params.Input] == [1, 1]
    rhino.client.call("gh_connect", source="count", target="s", target_input="count", keep_existing=False)
    assert len(comp.Params.Input[0].Sources) == 1
    with pytest.raises(BridgeError, match="has no input named 'zzz'"):
        rhino.client.call("gh_connect", source="count", target="s", target_input="zzz")
    g = rhino.client.call("gh_group", name="kazi", components=[sl["guid"], tg["guid"], "s"])
    assert len(objs(rhino, "Group")[0].members) == 3 and g["group"]
    rhino.client.call("gh_disconnect", target="s", target_input="count")
    assert comp.Params.Input[0].Sources == []


def test_geometry_input_references_selection(rhino):
    rhino.rhino.selected.extend([rhino.rhino.make_object("Brep"), rhino.rhino.make_object("Curve")])
    r = rhino.client.call("gh_add_geometry_input", nickname="facade")
    param = objs(rhino, "ParamGeometry")[0]
    assert r["objects"] == 2 and param.NickName == "facade"
    assert all(g.ReferenceID is not None and g.loaded for g in param.PersistentData)


def test_list_delete_solve_and_free_spot(rhino):
    rhino.client.call("gh_add_component", name="Divide Curve", nickname="div")
    listing = rhino.client.call("gh_list", filter="div")
    assert listing["count"] == 1
    objs(rhino, "Component")[0].messages = [("Warning", "Input parameter Curve failed to collect data")]
    assert rhino.client.call("gh_solve")["problems"][0]["nickname"] == "div"
    objs(rhino, "Component")[0].Attributes.Bounds.Bottom = 420
    assert rhino.client.call("gh_free_spot")["y"] == 500
    rhino.client.call("gh_delete", component="div")
    assert rhino.client.call("gh_list")["count"] == 0


@pytest.mark.parametrize("rhino", [{"open_canvas": False}], indirect=True)
def test_grasshopper_closed(rhino):
    with pytest.raises(BridgeError, match="Grasshopper is not open"):
        rhino.client.call("gh_list")
    assert rhino.app.scripts == ["_-Grasshopper _Window _Show _Enter"]


def test_restart_replaces_old_bridge(rhino):
    rhino.mod.PORT = 0
    rhino.mod.main()
    first = rhino.sc.sticky["rhino_ai_mods_bridge"]
    rhino.mod.main()
    second = rhino.sc.sticky["rhino_ai_mods_bridge"]
    assert first is not second and not first.running and second.running
    second.stop()
