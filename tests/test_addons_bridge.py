"""The add-on bridge commands (bridge/kazi_addons.py) and every add-on recipe, run through the
real bridge script against a fake Grasshopper that has the catalogued plug-ins installed."""

import importlib.util
import pathlib

import pytest

from fakes import addon_fakes, dotnet
from rhino_ai_mods.addons import catalog
from rhino_ai_mods.addons.graph import GraphBuilder, GraphPlan
from rhino_ai_mods.addons.recipes import ADDON_RECIPES, EXAMPLES, match_addon_recipe
from rhino_ai_mods.addons.registry import ADDONS
from rhino_ai_mods.bridge_client import BridgeClient, BridgeError

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge" / "rhino_ai_bridge.py"


def start(addons=None, **fake_kwargs):
    env = dotnet.install()
    addon_fakes.extend(env, addons, **fake_kwargs)
    spec = importlib.util.spec_from_file_location("rhino_ai_bridge_under_test", BRIDGE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    bridge = mod.Bridge(port=0)
    bridge.start()
    env.mod, env.bridge = mod, bridge
    env.client = BridgeClient(port=bridge.sock.getsockname()[1], timeout=10)
    return env


def stop(env):
    env.client.close()
    env.bridge.stop()
    dotnet.uninstall()


@pytest.fixture
def rhino(request):
    env = start(**getattr(request, "param", {}))
    yield env
    stop(env)


def canvas(env, name):
    return [o for o in env.gh.doc.Objects if o.Name == name]


# --------------------------------------------------------------------------- #
# bridge commands
# --------------------------------------------------------------------------- #

def test_extension_is_loaded_with_the_bridge(rhino):
    assert rhino.mod.LOADED_EXTENSIONS and rhino.mod.LOADED_EXTENSIONS[0].startswith("kazi_addons")
    for cmd in ("gh_plugins", "gh_search_components", "gh_component_info", "gh_resolve", "gh_place",
                "gh_wire", "gh_set_input", "gh_add_panel", "gh_inspect", "gh_component_dump"):
        assert cmd in rhino.mod.COMMANDS


def test_plugins_lists_libraries_and_tabs(rhino):
    r = rhino.client.call("gh_plugins")
    names = {lib["name"]: lib for lib in r["libraries"]}
    assert names["LunchBox"]["components"] == len(catalog.load().of("lunchbox"))
    assert names["Grasshopper"]["core"] is True and names["LunchBox"]["core"] is False
    assert r["categories"]["Ladybug"] > 50 and r["categories"]["Kangaroo2"] == 110


def test_search_by_words_and_scope(rhino):
    r = rhino.client.call("gh_search_components", query="quad panels")
    assert r["components"][0]["name"] == "Quad Panels" and r["components"][0]["library"] == "LunchBox"
    r = rhino.client.call("gh_search_components", query="sun", categories=["Ladybug"], limit=50)
    assert {"LB SunPath", "LB Direct Sun Hours"} <= {c["name"] for c in r["components"]}
    assert all(c["category"] == "Ladybug" for c in r["components"])
    r = rhino.client.call("gh_search_components", query="tween", with_params=True)
    assert all("inputs" in c for c in r["components"]) and r["count"] >= 5
    assert rhino.client.call("gh_search_components", query="zzzz nothing")["count"] == 0


def test_component_info_reads_params_without_touching_the_canvas(rhino):
    r = rhino.client.call("gh_component_info", name="Diagrid Structure")
    assert [p["name"] for p in r["inputs"]] == ["Surface", "U Divisions", "V Divisions", "Type"]
    assert [p["nickname"] for p in r["outputs"]] == ["Lines", "Nodes"]
    assert rhino.gh.doc.Objects == []
    with pytest.raises(BridgeError, match="No Grasshopper component named 'Flux Capacitor'"):
        rhino.client.call("gh_component_info", name="Flux Capacitor")


def test_resolve_prefers_the_wanted_plugin_over_a_namesake(rhino):
    # "Offset Surface" exists in Grasshopper's Surface tab and in Pufferfish
    r = rhino.client.call("gh_resolve", components=[
        {"names": ["Offset Surface"], **ADDONS["pufferfish"].scope()},
        {"names": ["Offset Surface"], "categories": ["Surface"]},
        {"names": ["Mesh Edges"], **ADDONS["weaverbird"].scope()},
        {"names": ["Hex"], **ADDONS["lunchbox"].scope()},
    ])
    cats = [c["category"] for c in r["components"]]
    assert cats[:3] == ["Pufferfish", "Surface", "Weaverbird"] and r["missing"] == 0
    assert r["components"][2]["name"] == "Weaverbird's Mesh Edges"


@pytest.mark.parametrize("rhino", [{"addons": ["lunchbox"]}], indirect=True)
def test_resolve_reports_missing_plugin_even_when_a_namesake_exists(rhino):
    r = rhino.client.call("gh_resolve", components=[
        {"names": ["Offset Surface"], **ADDONS["pufferfish"].scope()},   # only the built-in exists
        {"names": ["Solver"], **ADDONS["kangaroo2"].scope()},
        {"names": ["Quad Panels"], **ADDONS["lunchbox"].scope()}])
    assert [c["found"] for c in r["components"]] == [False, False, True] and r["missing"] == 2
    assert r["components"][0]["closest"][0]["category"] == "Surface"


@pytest.mark.parametrize("rhino", [{"weaverbird_prefix": False}], indirect=True)
def test_weaverbird_resolves_with_or_without_its_prefix(rhino):
    r = rhino.client.call("gh_place", names=["Weaverbird's Catmull-Clark Subdivision"],
                          **ADDONS["weaverbird"].scope())
    assert r["resolved"]["name"] == "Catmull-Clark Subdivision"


def test_place_sets_typed_in_values_and_reports_bad_ones(rhino):
    r = rhino.client.call("gh_place", names=["Quad Panels"], x=10, y=20,
                          set={"U Divisions": 12, "V": 7, "Nope": 1}, **ADDONS["lunchbox"].scope())
    comp = canvas(rhino, "Quad Panels")[0]
    u, v = comp.Params.Input[1], comp.Params.Input[2]
    assert [g.Value for g in u.PersistentData] == [12] and type(u.PersistentData[0]).__name__ == "GH_Integer"
    assert [g.Value for g in v.PersistentData] == [7]
    assert len(r["problems"]) == 1 and "'Nope'" in r["problems"][0] and "U Divisions (U)" in r["problems"][0]
    assert (comp.Attributes.Pivot.X, comp.Attributes.Pivot.Y) == (10.0, 20.0)


def test_wire_matches_loosely_and_flattens(rhino):
    solver = rhino.client.call("gh_place", names=["Solver"], **ADDONS["kangaroo2"].scope())["guid"]
    edges = rhino.client.call("gh_place", names=["EdgeLengths"], **ADDONS["kangaroo2"].scope())["guid"]
    anchor = rhino.client.call("gh_place", names=["Anchor"], **ADDONS["kangaroo2"].scope())["guid"]
    r = rhino.client.call("gh_wire", source=edges, target=solver, source_output=["EL"],
                          target_input=["Goal Objects", "Goals"], mapping="flatten")
    assert r["target_input"] == "GoalObjects"
    rhino.client.call("gh_wire", source=anchor, target=solver, target_input=["goalobjects"])
    goals = canvas(rhino, "Solver")[0].Params.Input[0]
    assert len(goals.Sources) == 2 and goals.DataMapping == "Flatten"
    with pytest.raises(BridgeError, match=r"no input named 'Nope' \(it has: GoalObjects"):
        rhino.client.call("gh_wire", source=anchor, target=solver, target_input=["Nope"])
    rhino.client.call("gh_wire", source=anchor, target=solver, target_input=["Nope", 1])  # index fallback
    assert len(canvas(rhino, "Solver")[0].Params.Input[1].Sources) == 1
    with pytest.raises(BridgeError, match="mapping must be"):
        rhino.client.call("gh_wire", source=anchor, target=solver, mapping="sideways")


def test_set_input_types_values_and_refuses_script_inputs(rhino):
    g = rhino.client.call("gh_place", names=["Offset Surface"], **ADDONS["pufferfish"].scope())["guid"]
    assert rhino.client.call("gh_set_input", component=g, input="Distance", value=0.25)["values"] == 1
    rhino.client.call("gh_set_input", component=g, input="Create Solid", value="yes")
    comp = canvas(rhino, "Offset Surface")[0]
    assert comp.Params.Input[1].PersistentData[0].Value == 0.25
    assert comp.Params.Input[3].PersistentData[0].Value is True
    rhino.client.call("gh_set_input", component=g, input="Distance", value=[1, 2, 3])
    assert [v.Value for v in comp.Params.Input[1].PersistentData] == [1.0, 2.0, 3.0]
    lb = rhino.client.call("gh_place", names=["LB SunPath"], **ADDONS["ladybug"].scope())["guid"]
    with pytest.raises(BridgeError, match="can't hold a value of its own"):
        rhino.client.call("gh_set_input", component=lb, input="_scale_", value=2)


def test_panel_inspect_delete_many_and_dump(rhino):
    p = rhino.client.call("gh_add_panel", nickname="layer", text="facade::glass", x=5, y=6)
    panel = rhino.gh.doc.Objects[0]
    assert panel.UserText == "facade::glass" and panel.NickName == "layer"
    assert rhino.client.call("gh_inspect", component=p["guid"])["nickname"] == "layer"
    assert rhino.client.call("gh_delete_many", components=[p["guid"], "not-there"])["removed"] == 1
    assert rhino.gh.doc.Objects == []
    d = rhino.client.call("gh_component_dump", categories=["LunchBox"], limit=50, with_params=True)
    assert d["total"] == len(catalog.load().of("lunchbox")) and len(d["components"]) == 50
    assert "inputs" in d["components"][0]
    total = rhino.client.call("gh_component_dump", limit=1)["total"]
    assert total > 1300


def test_hops_path(rhino):
    g = rhino.client.call("gh_place", names=["Hops"])["guid"]
    rhino.client.call("gh_hops_set_path", component=g, path="C:\\defs\\tower.gh")
    assert canvas(rhino, "Hops")[0].RemoteDefinitionLocation == "C:\\defs\\tower.gh"
    q = rhino.client.call("gh_place", names=["Quad Panels"])["guid"]
    with pytest.raises(BridgeError, match="not a Hops component"):
        rhino.client.call("gh_hops_set_path", component=q, path="x")


def test_original_commands_still_work_next_to_the_extension(rhino):
    assert rhino.client.call("gh_add_component", name="Loft")["name"] == "Loft"
    assert rhino.client.call("ping")["grasshopper_open"] is True


# --------------------------------------------------------------------------- #
# every recipe, built through the bridge
# --------------------------------------------------------------------------- #

@pytest.fixture
def shared():
    env = start()
    yield env
    stop(env)


@pytest.mark.parametrize("phrase,recipe", EXAMPLES)
def test_every_example_builds_cleanly(shared, phrase, recipe):
    env = shared
    env.gh.doc.Objects.clear()
    env.sc.sticky.pop("kazi_builds", None)
    env.rhino.selected[:] = [env.rhino.make_object("Brep", "wall")]
    plan = match_addon_recipe(phrase)
    assert plan.recipe == recipe
    result = GraphBuilder(env.client, confirm=False).build(plan)
    assert result.errors == [], result.errors          # every wire found its parameter
    assert result.status == "built"
    placed = {str(o.InstanceGuid) for o in env.gh.doc.Objects}
    assert set(result.components) <= placed and result.script in placed
    # every plug-in component on the canvas really comes from an add-on the plan names
    allowed = {c for a in plan.addons for c in ADDONS[a].categories}
    tabs = [o.tab for o in env.gh.doc.Objects if hasattr(o, "tab")]
    assert set(tabs) <= allowed
    assert len(tabs) == len([n for n in plan.components() if n.addon])
    build = env.sc.sticky["kazi_builds"][-1]
    assert build["title"] == plan.title and build["recipe"] == recipe and build["script"] == result.script
    groups = [o for o in env.gh.doc.Objects if type(o).__name__ == "Group"]
    assert len(groups) == 1 and len(groups[0].members) == len(result.components)


def test_lunchbox_panels_wiring_in_detail(shared):
    env = shared
    env.gh.doc.Objects.clear()
    env.rhino.selected[:] = [env.rhino.make_object("Brep", "wall")]
    plan = match_addon_recipe("panelize this facade with lunchbox, twelve by eight, with frames")
    result = GraphBuilder(env.client, confirm=False).build(plan)
    assert result.status == "built"
    quad = canvas(env, "Quad Panels")[0]
    srf, u, v = quad.Params.Input
    assert srf.Sources[0].NickName == "surface"        # from the pick-surface script
    assert (u.Sources[0].NickName, u.Sources[0].value) == ("u", 12)
    assert (v.Sources[0].NickName, v.Sources[0].value) == ("v", 8)
    frame = canvas(env, "Panel Frame")[0]
    assert frame.Params.Input[0].Sources[0] is quad.Params.Output[0]
    assert frame.Params.Input[1].Sources[0].NickName == "frame"
    assert result.script == str(frame.InstanceGuid)
    xs = {o.NickName: o.Attributes.Pivot.X for o in env.gh.doc.Objects if o.Attributes}
    assert xs["facade"] < xs["pick surface"] < xs["Quads"] < xs["Frame"]


def test_kangaroo_goals_are_all_flattened_into_the_solver(shared):
    env = shared
    env.gh.doc.Objects.clear()
    result = GraphBuilder(env.client, confirm=False).build(match_addon_recipe("hanging shell with kangaroo"))
    assert result.status == "built"
    solver = canvas(env, "Solver")[0]
    goals = solver.Params.Input[0]
    assert len(goals.Sources) == 4 and goals.DataMapping == "Flatten"   # edges, anchors, show, loads
    assert solver.Params.Input[8].Sources[0].NickName == "run"
    anchor = canvas(env, "Anchor")[0]
    assert anchor.Params.Input[0].Sources[0].NickName == "NakedPts"


def test_wallacei_uses_the_sliders_and_output_of_the_last_build(shared):
    env = shared
    env.gh.doc.Objects.clear()
    env.sc.sticky.pop("kazi_builds", None)
    env.rhino.selected[:] = [env.rhino.make_object("Brep", "wall")]
    builder = GraphBuilder(env.client, confirm=False)
    first = builder.build(match_addon_recipe("lunchbox diamond panels"))
    second = builder.build(match_addon_recipe("optimize this with wallacei"))
    assert second.status == "built" and second.warnings == []
    wx = canvas(env, "Wallacei X")[0]
    assert sorted(s.NickName for s in wx.Params.Input[0].Sources) == ["u", "v"]
    assert len(wx.Params.Input[1].Sources) == 2
    diamond = canvas(env, "Diamond Panels")[0]
    assert wx.Params.Input[3].Sources[0] is diamond.Params.Output[0]
    assert first.script == str(diamond.InstanceGuid)
    # undo removes only the Wallacei set-up
    env.client.call("kazi_undo_build")
    assert not canvas(env, "Wallacei X") and canvas(env, "Diamond Panels")


def test_wallacei_without_a_previous_build_warns(shared):
    env = shared
    env.gh.doc.Objects.clear()
    env.sc.sticky.pop("kazi_builds", None)
    result = GraphBuilder(env.client, confirm=False).build(match_addon_recipe("wallacei"))
    assert result.status == "built" and any("Nothing built with kazi yet" in w for w in result.warnings)


def test_confirm_dialog_can_cancel(shared):
    env = shared
    env.gh.doc.Objects.clear()
    env.app.dialog_answer = False
    try:
        result = GraphBuilder(env.client, confirm=True).build(match_addon_recipe("lunchbox hexagons"))
    finally:
        env.app.dialog_answer = True
    assert result.status == "cancelled" and env.gh.doc.Objects == []
    title, message = env.app.dialogs[-1]
    assert "LunchBox" in title and "Uses: LunchBox" in message and "Hexagon Cells" in message


def test_missing_addon_builds_nothing_and_says_how_to_install():
    env = start(addons=["lunchbox"])
    try:
        result = GraphBuilder(env.client, confirm=True).build(match_addon_recipe("tween these curves with pufferfish"))
        assert result.status == "missing_addon" and env.gh.doc.Objects == [] and env.app.dialogs == []
        assert "Tween Through Curves" in result.errors[0] and "Pufferfish" in result.errors[0]
        assert any("PackageManager" in n and "Pufferfish" in n for n in result.notes)
        assert any("can't build" in line for line in env.app.lines)
        result = GraphBuilder(env.client, confirm=False).build(match_addon_recipe("ladybug sun path"))
        assert result.status == "missing_addon" and any("food4rhino" in n for n in result.notes)
    finally:
        stop(env)


def test_failed_placement_cleans_up(shared):
    env = shared
    env.gh.doc.Objects.clear()
    plan = GraphPlan("broken", "x")
    plan.slider("a", 1, 0, 2)
    plan.component("ok", ["Quad Panels"], "lunchbox")
    plan.component("hops", ["Quad Panels"], "lunchbox", hops_path="C:\\x.gh")   # not a Hops: fails
    result = GraphBuilder(env.client, confirm=False).build(plan)
    assert result.status == "failed" and "not a Hops component" in result.errors[0]
    assert env.gh.doc.Objects == []


def test_bad_wire_is_reported_but_the_rest_is_built(shared):
    env = shared
    env.gh.doc.Objects.clear()
    plan = GraphPlan("half", "x")
    s = plan.slider("a", 1, 0, 2)
    c = plan.component("q", ["Quad Panels"], "lunchbox")
    plan.wire(s, c, ["Wrong Name"])
    plan.wire(s, c, ["U"])
    result = GraphBuilder(env.client, confirm=False).build(plan)
    assert result.status == "built_with_errors"
    assert "Wrong Name" in result.errors[0] and "Surface (Srf)" in result.errors[0]
    assert len(canvas(env, "Quad Panels")[0].Params.Input[1].Sources) == 1


def test_optional_component_is_left_out_when_missing():
    env = start(addons=["lunchbox"])
    try:
        plan = GraphPlan("opt", "x")
        q = plan.component("q", ["Quad Panels"], "lunchbox")
        o = plan.component("o", ["Mesh Thicken"], "weaverbird", optional=True)
        plan.wire(q, o, [0])
        result = GraphBuilder(env.client, confirm=False).build(plan)
        assert result.status == "built" and result.warnings == ["left out 'Mesh Thicken' (not installed)"]
        assert len(result.components) == 1
    finally:
        stop(env)


def test_old_bridge_without_the_extension_gives_a_clear_message(shared):
    env = shared
    saved = env.mod.COMMANDS.pop("gh_resolve")
    try:
        with pytest.raises(BridgeError, match="Run KaziStart in Rhino again"):
            GraphBuilder(env.client, confirm=False).build(match_addon_recipe("lunchbox"))
    finally:
        env.mod.COMMANDS["gh_resolve"] = saved


def test_every_addon_has_a_recipe_and_examples():
    assert set(ADDON_RECIPES) == set(ADDONS)
    covered = {match_addon_recipe(p).addons[0] if match_addon_recipe(p).addons else "wallacei"
               for p, _ in EXAMPLES}
    assert covered >= set(ADDONS) - {"wallacei"} and any(r == "wallacei_setup" for _, r in EXAMPLES)
