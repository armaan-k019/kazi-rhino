"""Add-on catalogue, speech matching, recipes, planner wrappers, audit, CLI, MCP and voice."""

import asyncio
import importlib.util
import json
import os
import pathlib
import sys
import types

import pytest

from fakes import addon_fakes, dotnet
from fakes import rhinocommon as rc
from rhino_ai_mods.addons import audit, catalog, cli, recipes
from rhino_ai_mods.addons.graph import GraphBuilder, GraphPlan, describe
from rhino_ai_mods.addons.planner import (AddonBuilder, AddonPlanner, named_component,
                                          parse_graph, single_component)
from rhino_ai_mods.addons.registry import ADDONS, mentioned
from rhino_ai_mods.bridge_client import BridgeClient
from rhino_ai_mods.gh.builder import Builder
from rhino_ai_mods.gh.planner import Planner
from rhino_ai_mods.gh.recipes import Plan
from rhino_ai_mods.voice.pipeline import VoicePipeline, is_grasshopper_request

ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "bridge" / "rhino_ai_bridge.py"
CAT = catalog.load()


# --------------------------------------------------------------------------- #
# catalogue
# --------------------------------------------------------------------------- #

def test_catalogue_covers_all_ten_addons():
    assert set(CAT.addons()) == set(ADDONS) and len(ADDONS) == 10
    sizes = {a: len(CAT.of(a)) for a in ADDONS}
    assert sizes["lunchbox"] > 150 and sizes["ladybug"] > 500 and sizes["kangaroo2"] == 110
    assert sizes["pufferfish"] > 300 and all(n >= 5 for n in sizes.values())


def test_catalogue_rows_are_well_formed():
    for path in (ROOT / "src/rhino_ai_mods/addons/data").glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["id"] == path.stem and data["name"] and data["source"]
        names = [row[0] for row in data["components"]]
        assert all(isinstance(n, str) and n.strip() == n and n for n in names), path.name
        for row in data["components"]:
            assert len(row) == 6, (path.name, row[0])
            for side in (row[4], row[5]):
                assert side is None or all(len(p) == 3 and p[0] for p in side), (path.name, row[0])


def test_catalogue_find_and_search():
    c = CAT.find("quad panels", "lunchbox")
    assert c.name == "Quad Panels" and [i[0] for i in c.inputs] == ["Surface", "U Divisions", "V Divisions"]
    assert CAT.find("Weaverbird's Catmull-Clark Subdivision").addon == "weaverbird"
    assert CAT.find("ImportEPW").name == "LB Import EPW"                     # by nickname
    assert CAT.find("Solver", "kangaroo2") and CAT.find("Solver", "lunchbox") is None
    assert CAT.search("tween curves", "pufferfish")[0].name.startswith("Tween")
    assert CAT.search("sun path")[0].name == "LB SunPath"
    assert CAT.search("zzz") == []
    assert "Surface" in CAT.find("Diagrid Structure").line()
    assert CAT.find("Quad Panels").to_dict()["inputs"][1] == {"name": "U Divisions", "nickname": "U",
                                                              "type": CAT.find("Quad Panels").inputs[1][2]}


def test_every_probe_component_is_in_the_catalogue():
    for a in ADDONS.values():
        assert all(CAT.find(p, a.id) for p in a.probe), a.id
        assert a.install in ("package_manager", "installer", "built_in")
        assert a.install != "package_manager" or a.package
        assert a.title in a.install_hint()


# --------------------------------------------------------------------------- #
# speech
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("said,addon", [
    ("panelize this facade with LunchBox", "lunchbox"), ("use lunch box hexagons", "lunchbox"),
    ("lady bug sun path", "ladybug"), ("honeybee daylight model", "ladybug"),
    ("relax it with kanga roo", "kangaroo2"), ("weaver bird subdivision", "weaverbird"),
    ("puffer fish tween", "pufferfish"), ("bake with ele front", "elefront"),
    ("bake it with elephant", "elefront"), ("list layers with human", "human"),
    ("the human plugin layer table", "human"), ("optimise with wallace i", "wallacei"),
    ("run it with wallacei", "wallacei"), ("add hops", "hops"), ("rhino compute component", "hops"),
    ("send it to speckle", "speckle"),
])
def test_addon_names_as_spoken(said, addon):
    assert mentioned(said, strict=True) == [addon]
    assert is_grasshopper_request(said)          # naming an add-on routes to Grasshopper


@pytest.mark.parametrize("said", [
    "select previous", "tween curves", "a human scale figure", "offset surface", "mesh", "loft",
    "boolean union", "the bishops gate tower", "extrude curve", "move",
])
def test_plain_rhino_commands_are_not_addon_requests(said):
    assert mentioned(said, strict=True) == []
    assert not is_grasshopper_request(said)


def test_topics_imply_an_addon_only_when_not_strict():
    assert mentioned("show me the sun path") == ["ladybug"] and mentioned("show me the sun path", True) == []
    assert mentioned("tween these curves") == ["pufferfish"]
    assert mentioned("kangaroo tensile, then tween with pufferfish") == ["kangaroo2", "pufferfish"]
    assert mentioned("tween it and relax with kangaroo")[0] == "kangaroo2"   # a named add-on wins


# --------------------------------------------------------------------------- #
# recipes: reading the request
# --------------------------------------------------------------------------- #

def values(plan):
    return {n.id: n.value for n in plan.nodes if n.kind in ("slider", "toggle")}


@pytest.mark.parametrize("phrase,recipe", recipes.EXAMPLES)
def test_examples_pick_their_recipe_and_are_valid(phrase, recipe):
    plan = recipes.match_addon_recipe(phrase)
    assert plan.recipe == recipe and plan.validate() == []
    assert plan.main and plan.title and plan.summary
    assert describe(plan, 1).endswith("Build it in Grasshopper?")
    json.dumps(plan.to_dict())
    again = GraphPlan.from_dict(plan.to_dict())
    assert again.to_dict()["nodes"] == plan.to_dict()["nodes"] and again.wires == plan.wires


@pytest.mark.parametrize("phrase,recipe", recipes.EXAMPLES)
def test_recipe_names_agree_with_the_catalogue(phrase, recipe):
    """Every component exists in its add-on's list, and where the list knows the inputs and
    outputs, each wire names one of them (not just a position)."""
    plan = recipes.match_addon_recipe(phrase)
    known = {}
    for n in plan.components():
        if n.addon:
            comp = next((CAT.find(x, n.addon) for x in n.names if CAT.find(x, n.addon)), None)
            assert comp is not None, n.names
            known[n.id] = comp
    for w in plan.wires:
        for end, side, refs in ((w.dst, "inputs", w.inp), (w.src, "outputs", w.out)):
            comp = known.get(end)
            params = getattr(comp, side) if comp else None
            if not params or not refs:
                continue
            assert audit._match([{"name": n, "nickname": k} for n, k, _t in params],
                                [r for r in refs if not isinstance(r, int)]), (comp.name, side, refs)


def test_lunchbox_reads_counts_and_panel_types():
    p = recipes.lunchbox_panels("panelize this facade with lunchbox ten by twenty")
    assert values(p) == {"u": 10, "v": 20} and p.node("panels").names == ["Quad Panels"]
    assert values(recipes.lunchbox_panels("lunchbox diamond panels 14 x 9"))["v"] == 9
    assert values(recipes.lunchbox_panels("lunchbox with 12 panels across and 5 up")) == {"u": 12, "v": 5}
    assert values(recipes.lunchbox_panels("lunchbox")) == {"u": 10, "v": 6}
    for said, name in [("hexagons", "Hexagon Cells"), ("triangles", "Triangular Panels A"),
                       ("triangle panels b", "Triangle Panels B"), ("staggered", "Staggered Quad Panels"),
                       ("random quads", "Random Quad Panels"), ("skewed quads", "Skewed Quads"),
                       ("brick pattern", "Staggered Quad Panels")]:
        assert recipes.lunchbox_panels("lunchbox " + said).node("panels").names[0] == name
    p = recipes.lunchbox_panels("lunchbox space truss two metres deep, depth 2.5")
    assert p.recipe == "lunchbox_space_truss" and values(p)["depth"] == 2.5
    assert recipes.lunchbox_panels("lunchbox hexagonal structure").node("structure").names == ["Hexagonal Structure"]
    p = recipes.lunchbox_panels("lunchbox quads with frames")
    assert p.main == "frames" and values(p)["frame"] == 0.9


def test_weaverbird_chains_operations_in_order():
    p = recipes.weaverbird("weaverbird loop subdivision 3 levels then picture frame 0.4 and thicken 0.05")
    assert [n.names[1] for n in p.components()] == ["Loop Subdivision", "Picture Frame", "Mesh Thicken"]
    assert values(p)["level"] == 3 and values(p)["thickness"] == 0.05
    assert p.main == "thicken" and p.columns()["thicken"] > p.columns()["frame"] > p.columns()["subdivide"]
    assert recipes.weaverbird("weaverbird").node("subdivide").names[0] == "Weaverbird's Catmull-Clark Subdivision"


def test_kangaroo_pufferfish_elefront_human_variants():
    assert values(recipes.kangaroo_relax("kangaroo tensile membrane"))["length factor"] == 0.0
    hang = recipes.kangaroo_relax("kangaroo hanging cloth with load 2")
    assert values(hang)["load"] == 2 and "loads" in [n.id for n in hang.nodes]
    assert values(recipes.pufferfish("pufferfish tween 20 steps"))["count"] == 20
    assert recipes.pufferfish("tween these surfaces").recipe == "pufferfish_tween_surfaces"
    assert values(recipes.pufferfish("pufferfish offset by 0.35"))["distance"] == 0.35
    bake = recipes.elefront("bake this with elefront to layer facade panels")
    assert bake.node("layer").text == "facade panels" and bake.node("bake").value is False
    assert recipes.elefront("elefront get everything from layer site").node("layer").text == "site"
    layers = recipes.human("create layers called glass and mullions with human")
    assert layers.node("layer names").text == "glass\nmullions"
    assert recipes.human("human live pipeline of layer context").recipe == "human_pipeline"


def test_ladybug_weather_source_and_run_toggles():
    p = recipes.ladybug("ladybug sun path")
    assert p.node("weather address").text == recipes.EPW_HINT and "download weather" in [n.id for n in p.nodes]
    assert any("epwmap" in n for n in p.notes)
    p = recipes.ladybug(r"ladybug radiation study with C:\weather\london.epw grid size 0.5")
    assert p.node("weather file").text == r"C:\weather\london.epw"
    assert "download weather" not in [n.id for n in p.nodes] and not any("epwmap" in n for n in p.notes)
    assert values(p) == {"grid size": 0.5, "run": False}            # heavy studies never auto-run
    p = recipes.ladybug("sun hours https://example.org/w/LONDON.zip month 12 day 21")
    assert p.node("weather address").text == "https://example.org/w/LONDON.zip"
    assert values(p)["month"] == 12 and values(p)["run"] is False


def test_hops_and_speckle_take_addresses():
    p = recipes.hops(r"add a hops component for C:\defs\tower core.gh")
    assert p.node("hops").hops_path == r"C:\defs\tower core.gh"
    assert recipes.hops("hops").node("hops").hops_path is None and recipes.hops("hops").notes
    p = recipes.speckle("publish to speckle https://app.speckle.systems/projects/abc/models/def")
    assert p.node("model address").text.endswith("/models/def") and p.recipe == "speckle_publish"
    assert recipes.speckle("receive from speckle").node("objects").optional


# --------------------------------------------------------------------------- #
# helper scripts (run with a stand-in for RhinoCommon)
# --------------------------------------------------------------------------- #

@pytest.fixture
def geom():
    rhino = rc.install()
    g = rhino.Geometry

    class Mesh:
        made = []

        def __init__(self, n=0):
            self.n = n
            self.Vertices = types.SimpleNamespace(CombineIdentical=lambda a, b: True)
            self.Normals = types.SimpleNamespace(ComputeNormals=lambda: True)
            self.welded = self.compacted = False
            self.Vertices.Count = n

        def Append(self, other):
            self.n += other.n
            self.Vertices.Count = self.n

        def Weld(self, angle):
            self.welded = True

        def Compact(self):
            self.compacted = True

        @staticmethod
        def CreateFromBrep(brep, params):
            Mesh.made.append(params)
            return [Mesh(4) for _ in brep.Faces]

        @staticmethod
        def CreateFromSubD(subd, density):
            return Mesh(8)

    class MeshingParameters:
        FastRenderMesh = "fast"

    class SubD:
        pass

    g.Mesh, g.MeshingParameters, g.SubD = Mesh, MeshingParameters, SubD
    rc.BrepFace.DuplicateFace = lambda self, dup: self
    yield g
    del rc.BrepFace.DuplicateFace
    rc.uninstall()


def test_to_mesh_script(geom):
    wall = rc.vertical_facade(30, 12)
    env, msgs = rc.run_script(recipes.TO_MESH, geo=[wall, geom.Mesh(5), geom.SubD()], edge=0)
    assert env["mesh"].n == 4 + 5 + 8 and env["mesh"].welded and env["mesh"].compacted and not msgs
    assert geom.Mesh.made[-1] == "fast"
    env, _ = rc.run_script(recipes.TO_MESH, geo=[wall], edge=1.5)
    assert geom.Mesh.made[-1].MaximumEdgeLength == 1.5
    env, msgs = rc.run_script(recipes.TO_MESH, geo=None, edge=None)
    assert env["mesh"] is None and "Select a mesh" in msgs[0][1]


def test_pick_surface_script_takes_the_biggest_face(geom):
    small, big = rc.vertical_facade(2, 2), rc.vertical_facade(30, 12)
    env, msgs = rc.run_script(recipes.PICK_SURFACE, geo=[small, big])
    assert env["surface"] is big.Faces[0] and not msgs
    env, msgs = rc.run_script(recipes.PICK_SURFACE, geo=[])
    assert env["surface"] is None and "Select a surface" in msgs[0][1]


def test_objectives_script(geom):
    env, _ = rc.run_script(recipes.OBJECTIVES, geo=[rc.vertical_facade(10, 3).Faces[0], rc.vertical_facade(2, 5).Faces[0], "junk"])
    assert env["wlc_total_area"] == pytest.approx(40) and env["wlc_piece_count"] == -3


# --------------------------------------------------------------------------- #
# planner and builder wrappers
# --------------------------------------------------------------------------- #

class Backend:
    def __init__(self, reply):
        self.reply, self.seen = reply, []

    def complete(self, messages, max_tokens=0):
        self.seen.append(messages)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def test_planner_routes_between_addons_and_script_recipes():
    planner = AddonPlanner(Planner(None))
    assert isinstance(planner.plan("panelize this facade with lunchbox"), GraphPlan)
    assert isinstance(planner.plan("panelize this facade"), Plan)                 # built-in script recipe
    assert planner.plan("voronoi facade then optimize the cells").recipe == "voronoi_facade"
    assert planner.plan("voronoi facade with lunchbox").recipe == "lunchbox_quad"  # named add-on wins
    assert planner.plan("show me the sun path").recipe == "ladybug_sun_path"       # implied add-on
    with pytest.raises(LookupError):
        planner.plan("make something nice")
    assert planner.repair(Plan("t", "s", [], ["a"], "a = 1"), ["boom"]) is None


def test_request_naming_another_component_places_it_or_asks_the_model():
    assert named_component("use the lunchbox unroll brep component", "lunchbox").name == "Unroll Brep"
    assert named_component("lunchbox panels", "lunchbox") is None
    plan = AddonPlanner(Planner(None)).plan("add the lunchbox unroll brep component")
    assert plan.recipe == "lunchbox_component" and plan.node("component").names == ["Unroll Brep"]
    assert "Inputs to wire: Brep, Join Unrolled" in plan.notes[0]
    assert single_component(CAT.find("Hops")).validate() == []

    good = '''```json
{"title": "Unrolled panels", "summary": "Unroll the selected polysurface.",
 "nodes": [{"id": "shape", "kind": "geometry"}, {"id": "join", "kind": "toggle", "value": true},
           {"id": "unroll", "kind": "component", "names": ["Unroll Brep"], "addon": "lunchbox"}],
 "wires": [{"src": "shape", "dst": "unroll", "inp": ["Brep"]},
           {"src": "join", "dst": "unroll", "inp": "Join Unrolled"}], "main": "unroll"}
```'''
    backend = Backend(good)
    plan = AddonPlanner(Planner(backend)).plan("use lunchbox unroll brep on this and join them")
    assert plan.title == "Unrolled panels" and plan.recipe == "lunchbox_model" and plan.addons == ["lunchbox"]
    assert plan.wires[1].inp == ["Join Unrolled"]
    system = backend.seen[0][0]["content"]
    assert "Unroll Brep (Brep, Join Unrolled) -> Unrolled Brep" in system and "LunchBox" in system
    # a tested recipe is used without asking the model
    assert AddonPlanner(Planner(backend)).plan("lunchbox quad panels").recipe == "lunchbox_quad"
    assert len(backend.seen) == 1


@pytest.mark.parametrize("reply", [
    "sorry, no", "```json\n{not json}\n```",
    '```json\n{"title": "x", "nodes": [{"id": "a", "kind": "component", "names": ["Flux Capacitor"], "addon": "lunchbox"}], "wires": []}\n```',
    '```json\n{"title": "x", "nodes": [{"id": "a", "kind": "component", "names": ["Solver"], "addon": "kangaroo2"}], "wires": []}\n```',
    '```json\n{"title": "x", "nodes": [{"id": "a", "kind": "component", "names": ["Unroll Brep"], "addon": "lunchbox"}, {"id": "s", "kind": "script", "code": "import os"}], "wires": []}\n```',
    '```json\n{"title": "x", "nodes": [{"id": "a", "kind": "component", "names": ["Unroll Brep"], "addon": "lunchbox"}], "wires": [{"src": "a", "dst": "nope"}]}\n```',
    '```json\n{"title": "x", "nodes": [{"id": "a", "kind": "slider", "value": 1, "min": 0, "max": 2}], "wires": []}\n```',
    RuntimeError("quota"),
])
def test_unusable_model_answers_fall_back_to_placing_the_component(reply):
    if isinstance(reply, str):
        assert parse_graph(reply, "lunchbox") is None
    plan = AddonPlanner(Planner(Backend(reply))).plan("use lunchbox unroll brep on this")
    assert plan.recipe == "lunchbox_component"


# --------------------------------------------------------------------------- #
# against the simulated Rhino
# --------------------------------------------------------------------------- #

def start(addons=None):
    env = dotnet.install(commands=("Box", "SelPrev", "Loft", "TweenCurves", "Delete"))
    addon_fakes.extend(env, addons)
    spec = importlib.util.spec_from_file_location("bridge_for_addons", BRIDGE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    bridge = mod.Bridge(port=0)
    bridge.start()
    env.mod, env.bridge, env.port = mod, bridge, bridge.sock.getsockname()[1]
    env.client = BridgeClient(port=env.port, timeout=10)
    return env


@pytest.fixture
def rhino(request):
    env = start(getattr(request, "param", None))
    yield env
    env.client.close()
    env.bridge.stop()
    dotnet.uninstall()


def test_builder_wrapper_handles_both_kinds_of_plan(rhino):
    rhino.rhino.selected.append(rhino.rhino.make_object("Brep", "wall"))
    planner = AddonPlanner(Planner(None))
    builder = AddonBuilder(Builder(rhino.client, planner, confirm=False))
    a = builder.build(planner.plan("lunchbox triangles 6 by 4"))
    b = builder.build(planner.plan("build fins on the facade"))
    assert (a.status, b.status) == ("built", "built")
    builds = rhino.sc.sticky["kazi_builds"]
    assert [x["recipe"] for x in builds] == ["lunchbox_triangle", "fins"]
    assert builder.confirm is False and builder.max_repairs == 2      # passes through
    # KaziBake works on an add-on build: it bakes the main component's outputs
    rhino.client.call("kazi_undo_build")
    main = rhino.gh.doc.FindObject(a.script, True)
    main.Params.Output[0].VolatileData.append("panel-geometry")
    assert rhino.client.call("kazi_bake")["baked"] == {"Panels": 1}
    assert rhino.rhino.DocObjects and rhino.rhino.Layers if hasattr(rhino.rhino, "Layers") else True


def test_voice_pipeline_builds_addon_requests(rhino):
    rhino.rhino.selected.append(rhino.rhino.make_object("Brep", "wall"))
    planner = AddonPlanner(Planner(None))
    pipe = VoicePipeline(bridge=rhino.client, planner=planner,
                         builder=AddonBuilder(Builder(rhino.client, planner, confirm=True)))
    out = pipe.handle("Panelize this facade with LunchBox, ten by twenty.", mode="rhino")
    assert out.status == "built" and out.source == "lunchbox_quad" and out.build["errors"] == []
    assert "Quad Panels" in rhino.app.dialogs[0][1]                  # the confirm step
    assert pipe.handle("tween curves", mode="rhino").macro == "_TweenCurves"   # still a Rhino command
    out = pipe.handle("tween these curves", mode="grasshopper")
    assert out.status == "built" and out.source == "pufferfish_tween_curves"
    assert pipe.handle("ladybug sun path", mode="dictate").status == "not_a_command"
    dry = VoicePipeline(bridge=rhino.client, planner=planner, dry_run=True)
    out = dry.handle("relax this mesh with kangaroo", mode="rhino")
    assert out.status == "dry_run" and out.build["kind"] == "graph" and "Kangaroo" in out.detail


@pytest.mark.parametrize("rhino", [["lunchbox", "kangaroo2"]], indirect=True)
def test_voice_reports_a_missing_addon(rhino):
    planner = AddonPlanner(Planner(None))
    pipe = VoicePipeline(bridge=rhino.client, planner=planner,
                         builder=AddonBuilder(Builder(rhino.client, planner, confirm=True)))
    out = pipe.handle("weaverbird picture frame", mode="grasshopper")
    assert out.status == "missing_addon" and rhino.gh.doc.Objects == [] and rhino.app.dialogs == []
    assert any("PackageManager" in n and "Weaverbird" in n for n in out.build["notes"])


@pytest.mark.parametrize("rhino", [["lunchbox", "kangaroo2", "hops"]], indirect=True)
def test_status_and_audit(rhino, tmp_path):
    st = audit.status(rhino.client)
    assert st["installed"] == ["lunchbox", "kangaroo2", "hops"] and "ladybug" in st["missing"]
    assert st["addons"]["lunchbox"]["components"] == len(CAT.of("lunchbox"))
    assert st["addons"]["lunchbox"]["version"] == "1.0"
    assert "food4rhino" in st["addons"]["ladybug"]["install"]
    assert "PackageManager" in st["addons"]["weaverbird"]["install"]
    report = audit.audit(rhino.client, tmp_path / "audit.json")
    assert report["ok"] is True and json.loads((tmp_path / "audit.json").read_text())["ok"] is True
    assert report["recipes"]["lunchbox_quad"]["ok"] is True
    assert report["recipes"]["ladybug_sun_path"] == {"ok": None, "skipped": "add-on not installed"}
    assert report["catalog"]["lunchbox"]["listed_but_not_installed"] == []
    assert rhino.gh.doc.Objects == []                                   # an audit places nothing


def test_audit_catches_a_renamed_parameter_and_component(rhino, tmp_path):
    proxies = rhino.gh.Instances.ComponentServer.ObjectProxies
    quad = next(p for p in proxies if p.Desc.Name == "Quad Panels")
    make = quad.CreateInstance

    def renamed():
        obj = make()
        obj.Params.Input[1].Name = obj.Params.Input[1].NickName = "Columns"
        return obj
    quad.CreateInstance = renamed
    next(p for p in proxies if p.Desc.Name == "Diamond Panels").Desc.Name = "Rhombus Panels"
    report = audit.audit(rhino.client, tmp_path / "a.json")
    assert report["ok"] is False
    assert report["recipes"]["lunchbox_quad"]["ok"] is True       # still fits, by position
    assert "matched by position to 'Columns'" in report["recipes"]["lunchbox_quad"]["by_position"][0]
    assert "'Diamond Panels' is not installed" in report["recipes"]["lunchbox_diamond"]["problems"]
    assert report["catalog"]["lunchbox"]["listed_but_not_installed"] == ["Diamond Panels"]
    assert report["catalog"]["lunchbox"]["installed_but_not_listed"] == ["Rhombus Panels"]
    pf = audit.preflight(rhino.client, GraphPlan.from_dict({"title": "t", "nodes": [
        {"id": "s", "kind": "slider", "value": 1, "min": 0, "max": 2},
        {"id": "q", "kind": "component", "names": ["Quad Panels"], "addon": "lunchbox"}],
        "wires": [{"src": "s", "dst": "q", "inp": ["Rows"]}]}))
    assert pf["ok"] is False and "no input named ['Rows']" in pf["problems"][0]


def test_learn_saves_a_snapshot(rhino, tmp_path):
    r = audit.learn(rhino.client, tmp_path / "components.json", page=400)
    data = catalog.load_learned(tmp_path / "components.json")
    assert r["components"] == data["count"] == len(data["components"]) > 1300
    assert r["tabs"]["Kangaroo2"] == 110
    quad = next(c for c in data["components"] if c["name"] == "Quad Panels")
    assert [p["name"] for p in quad["inputs"]] == ["Surface", "U Divisions", "V Divisions"]
    assert catalog.load_learned(tmp_path / "nope.json") is None


def test_cli(rhino, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "BridgeClient", lambda timeout=900: BridgeClient(port=rhino.port, timeout=10))
    monkeypatch.setattr(audit, "AUDIT_PATH", tmp_path / "audit.json")
    monkeypatch.setattr(catalog, "LEARNED_PATH", tmp_path / "components.json")
    assert cli.main(["list"]) == 0
    assert '"panelize this facade with lunchbox"' in capsys.readouterr().out
    assert cli.main(["find", "tween", "through", "curves", "--offline", "--addon", "pufferfish"]) == 0
    assert "[Pufferfish] Tween Through Curves (Curves, Factor" in capsys.readouterr().out
    assert cli.main(["find", "diagrid"]) == 0
    assert "[LunchBox] Diagrid Structure (Surface, U Divisions, V Divisions, Type)" in capsys.readouterr().out
    assert cli.main(["build", "lunchbox hexagons", "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["recipe"] == "lunchbox_hexagon"
    assert cli.main(["build", "make it pretty"]) == 2
    capsys.readouterr()
    assert cli.main(["build", "lunchbox hexagons", "--yes"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "built"
    assert cli.main(["check"]) == 0
    out = capsys.readouterr().out
    assert "installed  LunchBox" in out and "ok       lunchbox_quad" in out
    assert cli.main(["learn"]) == 0 and (tmp_path / "components.json").exists()


def test_cli_without_rhino(monkeypatch, capsys):
    monkeypatch.setattr(cli, "BridgeClient", lambda timeout=900: BridgeClient(port=1, timeout=2))
    assert cli.main(["check"]) == 3
    assert "Rhino bridge" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# Claude's view: MCP client -> rhino-ai-mcp (subprocess) -> bridge -> fake Rhino
# --------------------------------------------------------------------------- #

mcp = pytest.importorskip("mcp")
from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402


def call_tools(port, calls):
    async def go():
        params = StdioServerParameters(command=sys.executable, args=["-m", "rhino_ai_mods.mcp_server"],
                                       env={**os.environ, "RHINO_AI_BRIDGE_PORT": str(port)})
        async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            names = {t.name for t in (await s.list_tools()).tools}
            out = []
            for name, args in calls:
                if callable(args):
                    args = args(out)
                res = await s.call_tool(name, args)
                text = "".join(c.text for c in res.content if getattr(c, "text", None))
                out.append(json.loads(text) if text.strip().startswith(("{", "[")) else text)
            return names, out
    return asyncio.run(go())


def test_mcp_addon_tools_end_to_end(rhino):
    rhino.rhino.selected.append(rhino.rhino.make_object("Brep", "wall"))
    names, out = call_tools(rhino.port, [
        ("gh_addons", {}),
        ("gh_find_component", {"query": "diagrid", "addon": "lunchbox"}),
        ("gh_find_component", {"query": "sun hours", "installed": False}),
        ("gh_addon_build", {"request": "panelize this facade with lunchbox 10 by 20"}),
        ("gh_addon_build", {"request": "hanging shell with kangaroo", "dry_run": True}),
        ("gh_addon_build", {"request": "make it nice"}),
        ("gh_place_component", {"name": "Mesh Thicken", "addon": "weaverbird", "set": {"Distance": 0.2}}),
        ("gh_place_component", {"name": "Catmull-Clark Subdivision", "addon": "weaverbird"}),
        ("gh_wire", lambda o: {"source": o[7]["guid"], "target": o[6]["guid"],
                               "source_output": "Output Mesh/Curves", "target_input": "mesh curves"}),
        ("gh_set_input", lambda o: {"component": o[7]["guid"], "input": "Level", "value": 3}),
        ("gh_inspect", lambda o: {"component": o[6]["guid"]}),
        ("gh_add_panel", {"text": "facade::glass", "nickname": "layer"}),
        ("gh_add_toggle", {"nickname": "run"}),
        ("gh_place_component", {"name": "Hops"}),
        ("gh_hops_set_path", lambda o: {"component": o[13]["guid"], "path": "http://127.0.0.1:5000/panels"}),
        ("gh_place_component", {"name": "Solver", "addon": "nope"}),
    ])
    assert {"gh_addons", "gh_find_component", "gh_place_component", "gh_wire", "gh_set_input",
            "gh_inspect", "gh_addon_build", "gh_build_graph", "gh_learn_components", "gh_add_panel",
            "gh_add_toggle", "gh_hops_set_path", "gh_build", "gh_connect"} <= names
    assert len(out[0]["installed"]) == 10 and out[0]["ask_for"][0]["say"]
    assert out[1]["components"][0]["name"] == "Diagrid Structure" and "inputs" in out[1]["components"][0]
    assert out[2]["source"] == "reference list" and out[2]["components"][0]["name"] == "LB Direct Sun Hours"
    assert out[3]["status"] == "built" and out[3]["errors"] == []
    assert out[4]["recipe"] == "kangaroo_hanging" and out[4]["kind"] == "graph"
    assert "No add-on recipe" in out[5]["error"]
    assert out[6]["resolved"]["category"] == "Weaverbird" and out[6]["x"] == 80.0     # a free spot was used
    assert out[8]["target_input"] == "M"
    assert out[9]["values"] == 1
    assert out[10]["inputs"][0]["sources"] and out[10]["nickname"]
    assert "unknown add-on" in out[15]["error"]
    hops = next(o for o in rhino.gh.doc.Objects if o.Name == "Hops")
    assert hops.RemoteDefinitionLocation == "http://127.0.0.1:5000/panels"


def test_mcp_build_graph_check_then_build(rhino):
    rhino.rhino.selected.append(rhino.rhino.make_object("Brep", "wall"))
    graph = {"title": "Diagrid with nodes", "summary": "LunchBox diagrid",
             "nodes": [{"id": "facade", "kind": "geometry"},
                       {"id": "u", "kind": "slider", "value": 8, "min": 1, "max": 40, "integer": True},
                       {"id": "grid", "kind": "component", "names": ["Diagrid Structure"],
                        "addon": "lunchbox", "set": {"V Divisions": 6}}],
             "wires": [{"src": "facade", "dst": "grid", "inp": "Surface"},
                       {"src": "u", "dst": "grid", "inp": ["U Divisions"]}], "main": "grid"}
    bad = json.loads(json.dumps(graph))
    bad["wires"][1]["inp"] = ["Columns"]
    worse = {**graph, "nodes": graph["nodes"] + [{"id": "x", "kind": "teleporter"}]}
    _, out = call_tools(rhino.port, [
        ("gh_build_graph", {**bad, "check_only": True}),
        ("gh_build_graph", {**graph, "check_only": True}),
        ("gh_build_graph", worse),
        ("gh_build_graph", graph),
    ])
    assert out[0]["ok"] is False and "Columns" in out[0]["problems"][0]
    assert out[1]["ok"] is True and out[1]["components"][0]["tab"] == "LunchBox"
    assert "unknown kind 'teleporter'" in out[2]["error"]
    assert out[3]["status"] == "built" and len(out[3]["components"]) == 3
    grid = next(o for o in rhino.gh.doc.Objects if o.Name == "Diagrid Structure")
    assert grid.Params.Input[2].PersistentData[0].Value == 6 and len(grid.Params.Input[1].Sources) == 1
