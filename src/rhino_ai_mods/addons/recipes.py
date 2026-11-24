"""Ready-made definitions for the free add-ons, picked from a spoken or typed request.

Each recipe returns a GraphPlan built from the add-on's own components. Component and input
names are the ones in the add-on's documentation (see data/*.json); several candidates are
given where versions differ, and the bridge matches them loosely.
"""

from __future__ import annotations

import re
from typing import Callable

from .graph import GraphPlan
from .registry import ADDONS, mentioned

# --------------------------------------------------------------------------- #
# reading numbers and names out of a request
# --------------------------------------------------------------------------- #

_NUM = r"(-?\d+(?:\.\d+)?)"


def _clean(request: str) -> str:
    from ..voice.rules import words_to_numbers  # noqa: PLC0415

    text = re.sub(r"[,;!?\"“”]|\.(?!\d)", " ", (request or "").lower())
    return words_to_numbers(re.sub(r"\s+", " ", text).strip())


def _number(text: str, words: str, default: float) -> float:
    """'level 2', 'thickness of 0.2', '3 levels'."""
    m = (re.search(rf"\b(?:{words})\b(?: of| is| at| to|:|=)? {_NUM}", text)
         or re.search(rf"{_NUM} ?(?:m |mm |cm )?(?:{words})\b", text))
    return float(m.group(1)) if m else default


def _uv(text: str, default: tuple[int, int]) -> tuple[int, int]:
    """'10 by 20', '10 x 20', '12 panels across and 8 up', 'u 10 v 6'."""
    m = (re.search(rf"\b(\d+) ?(?:by|x|times) ?(\d+)\b", text)
         or re.search(r"\bu ?(?:=|of)? ?(\d+)\D{0,12}\bv ?(?:=|of)? ?(\d+)", text)
         or re.search(r"\b(\d+) (?:\w+ ){0,2}(?:across|wide|horizontal\w*|columns?)\D{0,20}?(\d+) "
                      r"(?:\w+ ){0,2}(?:up|high|tall|vertical\w*|rows?)", text))
    if m:
        return max(1, int(m.group(1))), max(1, int(m.group(2)))
    return default


def _named(text: str, words: str, several: bool = False) -> str | None:
    """'layer called facade panels', 'on layer glass' -> the name.
    several=True keeps 'glass and mullions' together (a list of names)."""
    stop = r" with\b| using\b| in\b| from\b| then\b|$" + ("" if several else r"| and\b")
    m = re.search(rf"\b(?:{words})(?: called| named| name| is|:)? ([a-z0-9][\w :-]*?)(?={stop})", text)
    return m.group(1).strip() if m else None


def _path(request: str) -> str | None:
    """A web address or a Windows / UNC file path said or typed in the request."""
    m = re.search(r"(https?://\S+|[A-Za-z]:[\\/][^\n\"']+?\.(?:gh|ghx|epw|py)\b|\\\\[^\n\"']+)", request or "")
    return m.group(1).rstrip(".,") if m else None


# --------------------------------------------------------------------------- #
# script helpers shared by recipes (Rhino 8, Python 3 script component)
# --------------------------------------------------------------------------- #

PICK_SURFACE = r'''"""Pick the surface to work on from whatever is selected: a surface, or the biggest face
of a polysurface or extrusion."""
import Rhino.Geometry as rg
import Grasshopper

best, best_area = None, -1.0
for g in (geo or []):
    if isinstance(g, rg.Extrusion):
        g = g.ToBrep()
    if isinstance(g, rg.Surface):
        g = g.ToBrep()
    if not isinstance(g, rg.Brep):
        continue
    for face in g.Faces:
        one = face.DuplicateFace(False)
        amp = rg.AreaMassProperties.Compute(one)
        area = amp.Area if amp else 0.0
        if area > best_area:
            best, best_area = one, area
if best is None:
    ghenv.Component.AddRuntimeMessage(Grasshopper.Kernel.GH_RuntimeMessageLevel.Warning,
                                      "Select a surface or polysurface in Rhino.")
surface = best
'''

TO_MESH = r'''"""Turn whatever is selected (meshes, surfaces, polysurfaces, extrusions, SubDs) into one mesh."""
import Rhino.Geometry as rg
import Grasshopper

out = rg.Mesh()
params = rg.MeshingParameters.FastRenderMesh
if edge and edge > 0:
    params = rg.MeshingParameters()
    params.MaximumEdgeLength = float(edge)
    params.MinimumEdgeLength = float(edge) * 0.5
    params.GridAspectRatio = 1.0
    params.JaggedSeams = False
    params.SimplePlanes = False
for g in (geo or []):
    if isinstance(g, rg.Mesh):
        out.Append(g)
        continue
    if isinstance(g, rg.Extrusion):
        g = g.ToBrep()
    if isinstance(g, rg.Surface):
        g = g.ToBrep()
    if isinstance(g, rg.SubD):
        m = rg.Mesh.CreateFromSubD(g, 1)
        if m:
            out.Append(m)
        continue
    if isinstance(g, rg.Brep):
        for m in (rg.Mesh.CreateFromBrep(g, params) or []):
            out.Append(m)
if out.Vertices.Count == 0:
    ghenv.Component.AddRuntimeMessage(Grasshopper.Kernel.GH_RuntimeMessageLevel.Warning,
                                      "Select a mesh, surface or polysurface in Rhino.")
    mesh = None
else:
    out.Vertices.CombineIdentical(True, True)
    out.Weld(3.14159)
    out.Normals.ComputeNormals()
    out.Compact()
    mesh = out
'''

OBJECTIVES = r'''"""Example fitness values for Wallacei. Wallacei always MINIMISES every objective, so a value
you want bigger goes in negative. Replace these with your own measures."""
import Rhino.Geometry as rg

area, count = 0.0, 0
for g in (geo or []):
    count += 1
    try:
        amp = rg.AreaMassProperties.Compute(g)
        if amp:
            area += amp.Area
    except Exception:
        pass
wlc_total_area = area        # smaller total area
wlc_piece_count = -count     # more pieces (negative = maximise)
'''


# --------------------------------------------------------------------------- #
# LunchBox
# --------------------------------------------------------------------------- #

_LB_PANELS = (
    # key, spoken, component names, outputs worth knowing, extra numeric input
    ("diamond", r"diamond", ["Diamond Panels"], "Diamond Panels"),
    ("hexagon", r"hex", ["Hexagon Cells"], "Hexagon Cells"),
    ("triangle_b", r"triang\w* (?:panels? )?b\b", ["Triangle Panels B", "Triangular Panels B"], "Panels"),
    ("triangle_c", r"triang\w* (?:panels? )?c\b", ["Triangle Panels C", "Triangular Panels C"], "Panels"),
    ("triangle", r"triang", ["Triangular Panels A", "Triangle Panels A"], "Panels"),
    ("staggered", r"stagger|brick|running bond", ["Staggered Quad Panels"], "Panels"),
    ("random", r"random", ["Random Quad Panels"], "Panels"),
    ("skewed", r"skew", ["Skewed Quads"], "Full Panels"),
    ("quad", r"quad|square|rectang|grid|panel", ["Quad Panels"], "Panels"),
)

_LB_STRUCTURES = (
    ("space_truss", r"space ?(?:truss|frame)", ["Space Truss Structure 1"]),
    ("diagrid", r"dia ?grid|diagonal grid", ["Diagrid Structure"]),
    ("braced_grid", r"brac", ["Braced Grid 2-D Structure", "Braced Grid 1-D Structure"]),
    ("hex_structure", r"hex\w* struct|honeycomb struct", ["Hexagonal Structure"]),
    ("grid_structure", r"grid struct|grid shell|gridshell|struct", ["Grid Structure"]),
)


def _surface_input(plan: GraphPlan) -> str:
    geo = plan.geometry("facade", "the surface or polysurface selected in Rhino")
    pick = plan.script("pick surface", PICK_SURFACE, [{"name": "geo", "access": "list"}], ["surface"])
    plan.wire(geo, pick, "geo")
    return pick


def lunchbox_panels(request: str) -> GraphPlan:
    text = _clean(request)
    for key, spoken, names in _LB_STRUCTURES:
        if re.search(spoken, text):
            return _lunchbox_structure(text, key, names)
    key, _spoken, names, out_name = next((p for p in _LB_PANELS if re.search(p[1], text)),
                                         _LB_PANELS[-1])
    u, v = _uv(text, (10, 6))
    label = names[0]
    plan = GraphPlan(f"LunchBox {label.lower()}",
                     f"Panelise the selected surface with LunchBox {label}: {u} across, {v} up.",
                     recipe=f"lunchbox_{key}")
    srf = _surface_input(plan)
    su = plan.slider("u", u, 1, 60, integer=True, description="panels across")
    sv = plan.slider("v", v, 1, 60, integer=True, description="panels up")
    comp = plan.component("panels", names, "lunchbox", label=label)
    plan.wire(srf, comp, ["Surface", "Srf", 0])
    plan.wire(su, comp, ["U Divisions", "U", 1])
    plan.wire(sv, comp, ["V Divisions", "V", 2])
    plan.main = comp
    if key in ("hexagon", "skewed"):
        t = plan.slider("t", _number(text, "t|shift|parameter", 0.25), 0.0, 1.0,
                        description="shape parameter")
        plan.wire(t, comp, ["t Parameter", "t", 3])
    if key == "random":
        seed = plan.slider("seed", 1, 0, 100, integer=True)
        plan.wire(seed, comp, ["Random Seed", "S", 3])
    if re.search(r"\bframes?\b|mullion|border", text):
        scale = plan.slider("frame", _number(text, "frame|scale", 0.9), 0.1, 1.0,
                            description="size of the opening inside each panel (1 = no frame)")
        frame = plan.component("frames", ["Panel Frame"], "lunchbox", label="Panel Frame")
        plan.wire(comp, frame, ["Panel", 0], out=[out_name, 0])
        plan.wire(scale, frame, ["Scale Factor", "S", 1])
        plan.main = frame
    return plan


def _lunchbox_structure(text: str, key: str, names: list[str]) -> GraphPlan:
    u, v = _uv(text, (8, 6))
    plan = GraphPlan(f"LunchBox {names[0].lower()}",
                     f"Build a LunchBox {names[0]} on the selected surface: {u} by {v} bays.",
                     recipe=f"lunchbox_{key}")
    srf = _surface_input(plan)
    su = plan.slider("u", u, 1, 60, integer=True, description="bays across")
    sv = plan.slider("v", v, 1, 60, integer=True, description="bays up")
    comp = plan.component("structure", names, "lunchbox", label=names[0])
    plan.wire(srf, comp, ["Surface", "Srf", 0])
    plan.wire(su, comp, ["U Divisions", "U", 1])
    plan.wire(sv, comp, ["V Divisions", "V", 2])
    if key == "space_truss":
        depth = plan.slider("depth", _number(text, "depth|deep|thick\\w*", 1.0), 0.05, 5.0,
                            description="truss depth")
        plan.wire(depth, comp, ["Truss Depth", "D", 3])
    plan.main = comp
    return plan


# --------------------------------------------------------------------------- #
# Weaverbird
# --------------------------------------------------------------------------- #

def _wb(names: list[str]) -> list[str]:
    return [n for name in names for n in ("Weaverbird's " + name, name)]


def _mesh_input(plan: GraphPlan, edge: float = 0.0) -> str:
    geo = plan.geometry("shape", "the mesh, surface or polysurface selected in Rhino")
    e = plan.slider("mesh edge", edge, 0.0, 10.0,
                    description="longest mesh edge when a surface is meshed (0 = automatic)")
    mesh = plan.script("to mesh", TO_MESH, [{"name": "geo", "access": "list"}, "edge"], ["mesh"])
    plan.wire(geo, mesh, "geo")
    plan.wire(e, mesh, "edge")
    return mesh


def weaverbird(request: str) -> GraphPlan:
    text = _clean(request)
    ops = []   # (id, names, extra input: (slider id, value, lo, hi, integer, input names))
    if re.search(r"loop", text):
        ops.append(("subdivide", ["Loop Subdivision"],
                    ("level", _number(text, "levels?|times|iterations?", 2), 0, 4, True, ["Level", "L", 1])))
    elif re.search(r"catmull|subdivi|smooth", text):
        ops.append(("subdivide", ["Catmull-Clark Subdivision"],
                    ("level", _number(text, "levels?|times|iterations?", 2), 0, 4, True, ["Level", "L", 1])))
    if re.search(r"window", text):
        ops.append(("window", ["Mesh Window"],
                    ("inset", _number(text, "inset|distance|window|width", 0.2), 0.0, 5.0, False, ["Distance", "D", 1])))
    if re.search(r"frame", text):
        ops.append(("frame", ["Picture Frame"],
                    ("frame width", _number(text, "frame|distance|width", 0.2), 0.0, 5.0, False, ["Distance", "D", 1])))
    if re.search(r"stellat|spik|pyramid", text):
        ops.append(("stellate", ["Stellate/Cumulation", "Stellate"],
                    ("height", _number(text, "height|distance|spikes?", 0.5), -5.0, 5.0, False, ["Distance", "D", 1])))
    if re.search(r"thick", text):
        ops.append(("thicken", ["Mesh Thicken"],
                    ("thickness", _number(text, "thick\\w*|distance", 0.1), 0.0, 2.0, False, ["Distance", "D", 1])))
    if not ops:
        ops.append(("subdivide", ["Catmull-Clark Subdivision"], ("level", 2, 0, 4, True, ["Level", "L", 1])))

    title = "Weaverbird " + " + ".join(op[1][0].lower() for op in ops)
    plan = GraphPlan(title, "Run the selected shape through Weaverbird: "
                     + ", then ".join(op[1][0] for op in ops) + ".",
                     recipe="weaverbird_" + "_".join(op[0] for op in ops))
    prev, prev_out = _mesh_input(plan), ["mesh"]
    for op_id, names, (sid, value, lo, hi, integer, inp) in ops:
        comp = plan.component(op_id, _wb(names), "weaverbird", label=names[0])
        plan.wire(prev, comp, ["Mesh/Curves", "Mesh/Polylines", "Mesh", "M", 0], out=prev_out)
        s = plan.slider(sid, int(value) if integer else value, lo, hi, integer=integer)
        plan.wire(s, comp, inp)
        prev, prev_out = comp, ["Output Mesh/Curves", "OutMesh", "O", 0]
    plan.main = prev
    return plan


# --------------------------------------------------------------------------- #
# Kangaroo 2
# --------------------------------------------------------------------------- #

def kangaroo_relax(request: str) -> GraphPlan:
    text = _clean(request)
    hanging = bool(re.search(r"hang|catenary|shell|vault|gravity|drape|cloth|load", text))
    title = "Kangaroo hanging form" if hanging else "Kangaroo tensile relaxation"
    plan = GraphPlan(title, (
        "Hang the selected shape under load with its edges pinned (a catenary shell when flipped)."
        if hanging else
        "Relax the selected shape like a stretched membrane, with its open edges pinned."),
        recipe="kangaroo_hanging" if hanging else "kangaroo_tensile")
    mesh = _mesh_input(plan, edge=_number(text, "edge|mesh size|cell", 1.0))
    k2 = "kangaroo2"

    edges = plan.component("edge lengths", ["Edge Lengths", "EdgeLengths"], k2, label="Edge Lengths")
    plan.wire(mesh, edges, ["Mesh", "M", 0], out="mesh")
    factor = plan.slider("length factor", 1.0 if hanging else 0.0, 0.0, 2.0,
                         description="rest length of every edge as a factor of its current length "
                                     "(0 = shrink as far as possible, like a soap film)")
    plan.wire(factor, edges, ["LengthFactor", "Length Factor", 1])
    stiffness = plan.slider("stiffness", 10.0 if hanging else 1.0, 0.0, 100.0)
    plan.wire(stiffness, edges, ["Strength", 2])

    naked = plan.component("naked vertices", ["Naked Vertices", "NakedVertices", "NV"], k2,
                           label="Naked Vertices")
    plan.wire(mesh, naked, ["Mesh", "M", 0], out="mesh")
    anchor = plan.component("anchors", ["Anchor"], k2, label="Anchor")
    plan.wire(naked, anchor, ["Point", "P", 0], out=["NakedPts", "Naked Points", 3])

    show = plan.component("show", ["Show"], k2, label="Show")
    plan.wire(mesh, show, ["G", 0], out="mesh")

    solver = plan.component("solver", ["Solver"], k2, label="Solver")
    goals = ["GoalObjects", "Goal Objects", "Goals", 0]
    plan.wire(edges, solver, goals, out=["EL", 0], mapping="flatten")
    plan.wire(anchor, solver, goals, out=["A", 0], mapping="flatten")
    plan.wire(show, solver, goals, out=["G", 0], mapping="flatten")
    if hanging:
        loads = plan.component("loads", ["Vertex Loads", "VertexLoads"], k2, label="Vertex Loads")
        plan.wire(mesh, loads, ["Mesh", "M", 0], out="mesh")
        load = plan.slider("load", _number(text, "load|weight|gravity", 1.0), -10.0, 10.0,
                           description="load on every vertex; change the sign to flip up / down")
        plan.wire(load, loads, ["Strength", 1])
        plan.wire(loads, solver, goals, out=["L", 0], mapping="flatten")
    on = plan.toggle("run", True, description="pause the solver")
    plan.wire(on, solver, ["On"])
    plan.main = solver
    plan.notes.append("Right-click the Solver's Reset input and add a Button to start again from "
                      "the original shape.")
    return plan


# --------------------------------------------------------------------------- #
# Pufferfish
# --------------------------------------------------------------------------- #

def pufferfish(request: str) -> GraphPlan:
    text = _clean(request)
    pf = "pufferfish"
    if re.search(r"offset|thicken|shell", text) and "tween" not in text:
        dist = _number(text, "offset|distance|thick\\w*|by", 0.2)
        plan = GraphPlan("Pufferfish offset surface",
                         f"Offset the selected surface by {dist:g} with Pufferfish, as a closed solid.",
                         recipe="pufferfish_offset")
        srf = _surface_input(plan)
        d = plan.slider("distance", dist, -5.0, 5.0)
        solid = plan.toggle("solid", True, description="close the sides")
        both = plan.toggle("both sides", False)
        comp = plan.component("offset", ["Offset Surface"], pf, label="Offset Surface")
        plan.wire(srf, comp, ["Surface", "S", 0])
        plan.wire(d, comp, ["Distance", "D", 1])
        plan.wire(both, comp, ["Both Sides", "B", 2])
        plan.wire(solid, comp, ["Create Solid", "C", 3])
        plan.main = comp
        return plan

    surfaces = bool(re.search(r"surface|srf", text))
    meshes = bool(re.search(r"mesh", text))
    count = int(_number(text, "tweens?|steps?|curves|surfaces|in between|inbetween|copies", 8))
    kind = "surfaces" if surfaces else ("meshes" if meshes else "curves")
    if meshes:
        names, inp_a = ["Tween Two Meshes"], None
    elif surfaces:
        names, inp_a = ["Tween Through Surfaces"], ["Surfaces", "S", 0]
    else:
        names, inp_a = ["Tween Through Curves"], ["Curves", "C", 0]
    plan = GraphPlan(f"Pufferfish tween {kind}",
                     f"Blend between the selected {kind} with Pufferfish: {count} in-between shapes.",
                     recipe=f"pufferfish_tween_{kind}")
    geo = plan.geometry(kind, f"the {kind} selected in Rhino, in order")
    n = plan.slider("count", count, 1, 100, integer=True, description="number of in-between shapes")
    rng = plan.component("factors", ["Range"], categories=["Sets"], label="Range")
    plan.wire(n, rng, ["Steps", "N", 1])
    comp = plan.component("tween", names, pf, label=names[0])
    if meshes:
        plan.notes.append("Tween Two Meshes needs exactly two meshes with the same number of "
                          "vertices: wire the first into Mesh A and the second into Mesh B.")
    else:
        plan.wire(geo, comp, inp_a)
    plan.wire(rng, comp, ["Factor", "F"], out=["Range", "R", 0])
    plan.main = comp
    return plan


# --------------------------------------------------------------------------- #
# Elefront
# --------------------------------------------------------------------------- #

def elefront(request: str) -> GraphPlan:
    text = _clean(request)
    ef = "elefront"
    layer = _named(text, "layers?") or "kazi::baked"
    if re.search(r"referenc|get |grab|pull|read|bring in|from (?:the )?layer", text) and "bake" not in text:
        plan = GraphPlan("Elefront reference by layer",
                         f"Bring every Rhino object on layer \"{layer}\" into Grasshopper, live.",
                         recipe="elefront_reference")
        name = plan.panel("layer", layer, "layer to read")
        comp = plan.component("reference", ["Reference by Layer"], ef, label="Reference by Layer")
        plan.wire(name, comp, ["Layer name", "Layer", "L", 0])
        plan.main = comp
        return plan
    obj_name = _named(text, "named?|called") or ""
    plan = GraphPlan("Elefront bake with attributes",
                     f"Bake the selected geometry to layer \"{layer}\" with Elefront, keeping the "
                     "name and layer as attributes. Flip the bake toggle to bake.",
                     recipe="elefront_bake")
    geo = plan.geometry("geometry", "what to bake")
    lay = plan.panel("layer", layer, "layer to bake to")
    nm = plan.panel("name", obj_name or "kazi", "object name")
    atts = plan.component("attributes", ["EleFront Attributes", "Elefront Attributes", "EF Att"], ef,
                          label="EleFront Attributes")
    plan.wire(lay, atts, ["Layer", "L"])
    plan.wire(nm, atts, ["Name", "N"])
    go = plan.toggle("bake", False, description="set to True to bake")
    bake = plan.component("bake objects", ["Bake Objects"], ef, label="Bake Objects")
    plan.wire(geo, bake, ["Geometry", "G", 0])
    plan.wire(atts, bake, ["Attributes", "A", 1], out=["Attributes", "A", 0])
    plan.wire(go, bake, ["Bake", "B"])
    plan.main = bake
    plan.notes.append("Bake Objects is in 'push' mode by default: baking again replaces what it "
                      "baked before instead of piling up copies.")
    return plan


# --------------------------------------------------------------------------- #
# Human
# --------------------------------------------------------------------------- #

def human(request: str) -> GraphPlan:
    text = _clean(request)
    hu = "human"
    if re.search(r"creat|add|make|new|modif|set up", text) and "layer" in text:
        raw = _named(text, "layers?", several=True) or "kazi::concept"
        names = [n.strip() for n in re.split(r",| and ", raw) if n.strip()]
        plan = GraphPlan("Human create layers", "Create or update Rhino layers from Grasshopper "
                         "with Human: " + ", ".join(names) + ".", recipe="human_layers")
        p = plan.panel("layer names", "\n".join(names), "one layer per line; use :: for sub-layers")
        comp = plan.component("layers", ["Create/Modify Layers"], hu, label="Create/Modify Layers")
        plan.wire(p, comp, ["Layer Name", "L", 0])
        plan.main = comp
        plan.notes.append("For several layers, right-click the panel and untick 'Multiline Data' "
                          "so every line is its own layer.")
        return plan
    if re.search(r"pipeline|live|referenc|geometry on|objects on|everything on", text):
        layer = _named(text, "layers?") or "*"
        plan = GraphPlan("Human dynamic pipeline",
                         f"A live link to every Rhino object on layer \"{layer}\" (Human Dynamic "
                         "Geometry Pipeline).", recipe="human_pipeline")
        p = plan.panel("layer filter", layer, "layer name, * for all")
        comp = plan.component("pipeline", ["Dynamic Geometry Pipeline"], hu,
                              label="Dynamic Geometry Pipeline")
        plan.wire(p, comp, ["Layer Filter", "lay", 0])
        plan.main = comp
        return plan
    plan = GraphPlan("Human layer table", "List the Rhino document's layers, colours and "
                     "materials in Grasshopper with Human.", recipe="human_layer_table")
    auto = plan.toggle("auto update", True, description="refresh when layers change")
    comp = plan.component("layer table", ["Layer Table"], hu, label="Layer Table")
    plan.wire(auto, comp, ["Auto-Update", "AU", 1])
    plan.main = comp
    return plan


# --------------------------------------------------------------------------- #
# Ladybug Tools
# --------------------------------------------------------------------------- #

EPW_HINT = ("PASTE A WEATHER FILE ADDRESS HERE: open https://www.ladybug.tools/epwmap/ , click "
            "your city, copy the link of its .zip file and paste it over this text.")


def _weather(plan: GraphPlan, request: str) -> str:
    """Panel (address or .epw path) -> [LB Download Weather] -> LB Import EPW. Returns the importer."""
    lb = "ladybug"
    given = _path(request)
    epw = plan.component("import epw", ["LB Import EPW"], lb, label="LB Import EPW")
    if given and given.lower().endswith(".epw") and not given.lower().startswith("http"):
        src = plan.panel("weather file", given, "path of the .epw file")
        plan.wire(src, epw, ["_epw_file", 0])
    else:
        src = plan.panel("weather address", given or EPW_HINT, "web address of the weather .zip")
        dl = plan.component("download weather", ["LB Download Weather"], lb, label="LB Download Weather")
        plan.wire(src, dl, ["_weather_URL", 0])
        plan.wire(dl, epw, ["_epw_file", 0], out=["epw_file", 0])
        if not given:
            plan.notes.append("Paste a weather file address into the 'weather address' panel "
                              "(get one from ladybug.tools/epwmap). Until then the Ladybug "
                              "components stay empty.")
    return epw


def ladybug(request: str) -> GraphPlan:
    text = _clean(request)
    lb = "ladybug"
    if re.search(r"radiation|solar (?:gain|exposure|study|analysis)|irradia|insolation", text):
        grid = _number(text, "grid(?: size)?|cell|resolution", 1.0)
        plan = GraphPlan("Ladybug incident radiation",
                         "Yearly solar radiation falling on the selected geometry, coloured per "
                         f"grid cell ({grid:g} m). Flip 'run' to calculate.",
                         recipe="ladybug_radiation")
        epw = _weather(plan, request)
        sky = plan.component("sky matrix", ["LB Cumulative Sky Matrix"], lb, label="LB Cumulative Sky Matrix")
        plan.wire(epw, sky, ["_location"], out=["location"])
        plan.wire(epw, sky, ["_direct_rad"], out=["direct_normal_rad"])
        plan.wire(epw, sky, ["_diffuse_rad"], out=["diffuse_horizontal_rad"])
        geo = plan.geometry("geometry", "surfaces to study")
        size = plan.slider("grid size", grid, 0.1, 10.0, description="size of each test cell")
        run = plan.toggle("run", False, description="set to True to calculate")
        study = plan.component("radiation", ["LB Incident Radiation"], lb, label="LB Incident Radiation")
        plan.wire(sky, study, ["_sky_mtx"], out=["sky_mtx"])
        plan.wire(geo, study, ["_geometry"])
        plan.wire(size, study, ["_grid_size"])
        plan.wire(run, study, ["_run"])
        plan.main = study
        plan.notes.append("Wire buildings that cast shadows into 'context_'.")
        return plan

    if re.search(r"sun ?(?:light )?hours|hours of sun|direct sun|shadow study|overshadow", text):
        grid = _number(text, "grid(?: size)?|cell|resolution", 1.0)
        plan = GraphPlan("Ladybug direct sun hours",
                         "Hours of direct sun on the selected geometry over the chosen period "
                         f"(default: 21 June, all day), per {grid:g} m cell. Flip 'run' to calculate.",
                         recipe="ladybug_sun_hours")
        epw = _weather(plan, request)
        period = plan.component("period", ["LB Analysis Period"], lb, label="LB Analysis Period")
        month = plan.slider("month", int(_number(text, "month", 6)), 1, 12, integer=True)
        day = plan.slider("day", int(_number(text, "day", 21)), 1, 31, integer=True)
        for s, a, b in ((month, "_start_month_", "_end_month_"), (day, "_start_day_", "_end_day_")):
            plan.wire(s, period, [a])
            plan.wire(s, period, [b])
        sun = plan.component("sun path", ["LB SunPath"], lb, label="LB SunPath")
        plan.wire(epw, sun, ["_location"], out=["location"])
        plan.wire(period, sun, ["hoys_"], out=["hoys"])
        geo = plan.geometry("geometry", "surfaces to study")
        size = plan.slider("grid size", grid, 0.1, 10.0)
        run = plan.toggle("run", False, description="set to True to calculate")
        study = plan.component("sun hours", ["LB Direct Sun Hours"], lb, label="LB Direct Sun Hours")
        plan.wire(sun, study, ["_vectors"], out=["vectors"])
        plan.wire(geo, study, ["_geometry"])
        plan.wire(size, study, ["_grid_size"])
        plan.wire(run, study, ["_run"])
        plan.main = study
        plan.notes.append("Wire buildings that cast shadows into 'context_'.")
        return plan

    if re.search(r"wind", text):
        plan = GraphPlan("Ladybug wind rose", "A wind rose for the weather file: where the wind "
                         "comes from and how strong, over the year.", recipe="ladybug_wind_rose")
        epw = _weather(plan, request)
        rose = plan.component("wind rose", ["LB Wind Rose"], lb, label="LB Wind Rose")
        plan.wire(epw, rose, ["_data"], out=["wind_speed"])
        plan.wire(epw, rose, ["_wind_direction"], out=["wind_direction"])
        plan.main = rose
        return plan

    scale = _number(text, "scale|size", 1.0)
    plan = GraphPlan("Ladybug sun path", "Draw the sun path for the weather file's location at "
                     "the model origin.", recipe="ladybug_sun_path")
    epw = _weather(plan, request)
    s = plan.slider("scale", scale, 0.1, 20.0, description="size of the sun path")
    sun = plan.component("sun path", ["LB SunPath"], lb, label="LB SunPath")
    plan.wire(epw, sun, ["_location"], out=["location"])
    plan.wire(s, sun, ["_scale_"])
    plan.main = sun
    return plan


# --------------------------------------------------------------------------- #
# Wallacei
# --------------------------------------------------------------------------- #

def wallacei(request: str) -> GraphPlan:
    plan = GraphPlan("Wallacei optimisation",
                     "Set up Wallacei X on the last thing kazi built: its sliders become the "
                     "genes, and a small script measures the result as objectives to minimise.",
                     recipe="wallacei_setup")
    genes = plan.previous("sliders of the last build", "sliders")
    geo = plan.previous("result of the last build", "output")
    obj = plan.script("objectives", OBJECTIVES, [{"name": "geo", "access": "list"}],
                      ["wlc_total_area", "wlc_piece_count"])
    plan.wire(geo, obj, "geo")
    wx = plan.component("wallacei x", ["Wallacei X"], "wallacei", label="Wallacei X")
    plan.wire(genes, wx, ["Genes", 0])
    plan.wire(obj, wx, ["Objectives", 1], out="wlc_total_area")
    plan.wire(obj, wx, ["Objectives", 1], out="wlc_piece_count")
    plan.wire(geo, wx, ["Phenotype", 3])
    plan.main = wx
    plan.notes += [
        "Wallacei always minimises. Edit the 'objectives' script so each wlc_ output is a number "
        "you want smaller (put a minus in front of ones you want bigger).",
        "Double-click Wallacei X, set generation size and count, then press Start.",
    ]
    return plan


# --------------------------------------------------------------------------- #
# Hops
# --------------------------------------------------------------------------- #

def hops(request: str) -> GraphPlan:
    path = _path(request)
    plan = GraphPlan("Hops component",
                     "Place a Hops component" + (f" that runs {path}." if path else
                                                 " ready to point at a Grasshopper file or a web address."),
                     recipe="hops_place")
    plan.component("hops", ["Hops"], "hops", label="Hops", hops_path=path)
    plan.main = "hops"
    if not path:
        plan.notes.append("Right-click the Hops component > Path, and choose a .gh file or paste "
                          "a web address. Its inputs and outputs then appear. Or ask Claude: "
                          "gh_hops_set_path.")
    return plan


# --------------------------------------------------------------------------- #
# Speckle
# --------------------------------------------------------------------------- #

SPECKLE_HINT = ("PASTE YOUR SPECKLE MODEL ADDRESS HERE (open the model on app.speckle.systems "
                "and copy the address from the browser).")


def speckle(request: str) -> GraphPlan:
    text = _clean(request)
    sp = "speckle"
    url = _path(request)
    receive = bool(re.search(r"receiv|load|pull|get |download|bring in|import", text))
    plan = GraphPlan("Speckle load" if receive else "Speckle publish",
                     ("Load a Speckle model into Grasshopper." if receive else
                      "Publish the selected geometry to a Speckle model.")
                     + " Click the button on the component to run it.",
                     recipe="speckle_load" if receive else "speckle_publish")
    addr = plan.panel("model address", url or SPECKLE_HINT, "address of the Speckle model")
    model = plan.component("model", ["Speckle Model", "Speckle Model URL"], sp, label="Speckle Model")
    plan.wire(addr, model, ["URL", "Speckle URL", 0])
    if receive:
        load = plan.component("load", ["Load"], sp, label="Load")
        plan.wire(model, load, ["Speckle Model", "Model", 0])
        query = plan.component("objects", ["Query Objects", "Query Speckle Objects"], sp,
                               optional=True, label="Query Objects")
        plan.wire(load, query, ["Collection", 0], out=["Collection", 0])
        plan.main = load
    else:
        geo = plan.geometry("geometry", "what to send")
        coll = plan.component("collection", ["Create Collection"], sp, label="Create Collection")
        plan.wire(geo, coll, [0])
        pub = plan.component("publish", ["Publish"], sp, label="Publish")
        plan.wire(model, pub, ["Speckle Model", "Model", 0])
        plan.wire(coll, pub, ["Collection", 1], out=["Collection", 0])
        msg = plan.panel("message", "sent from Grasshopper with kazi", "version message")
        plan.wire(msg, pub, ["Version Message", "Message", 2])
        plan.main = pub
    if not url:
        plan.notes.append("Paste your Speckle model address into the 'model address' panel.")
    plan.notes.append("Sign in first with the Speckle Sign-In component or the Speckle desktop "
                      "manager. Publish / Load run when you click their button.")
    return plan


# --------------------------------------------------------------------------- #
# registry of recipes and matching
# --------------------------------------------------------------------------- #

# add-on id -> recipe factory. One factory per add-on; each reads the request to pick a variant.
ADDON_RECIPES: dict[str, Callable[[str], GraphPlan]] = {
    "lunchbox": lunchbox_panels,
    "weaverbird": weaverbird,
    "kangaroo2": kangaroo_relax,
    "pufferfish": pufferfish,
    "elefront": elefront,
    "human": human,
    "ladybug": ladybug,
    "wallacei": wallacei,
    "hops": hops,
    "speckle": speckle,
}

# Phrases to show the user / Claude, and to test with: (phrase, expected recipe)
EXAMPLES: list[tuple[str, str]] = [
    ("panelize this facade with lunchbox", "lunchbox_quad"),
    ("lunchbox diamond panels ten by twenty", "lunchbox_diamond"),
    ("hexagon cells with lunch box", "lunchbox_hexagon"),
    ("triangular panels with lunchbox and frames", "lunchbox_triangle"),
    ("lunchbox diagrid structure 12 by 8", "lunchbox_diagrid"),
    ("build a space truss with lunchbox depth 1.5", "lunchbox_space_truss"),
    ("subdivide this mesh with weaverbird level 2", "weaverbird_subdivide"),
    ("weaverbird picture frame and thicken it", "weaverbird_frame_thicken"),
    ("relax this mesh with kangaroo", "kangaroo_tensile"),
    ("make a hanging shell with kangaroo", "kangaroo_hanging"),
    ("tween these curves with pufferfish 12 steps", "pufferfish_tween_curves"),
    ("pufferfish offset surface by 0.3", "pufferfish_offset"),
    ("bake this with elefront to layer facade panels", "elefront_bake"),
    ("elefront reference everything from layer site", "elefront_reference"),
    ("list my layers with human", "human_layer_table"),
    ("create layers called glass and mullions with human", "human_layers"),
    ("ladybug sun path", "ladybug_sun_path"),
    ("run a sun hours study on this", "ladybug_sun_hours"),
    ("solar radiation study on the facade", "ladybug_radiation"),
    ("show me a wind rose", "ladybug_wind_rose"),
    ("optimize this with wallacei", "wallacei_setup"),
    ("add a hops component", "hops_place"),
    ("publish this to speckle", "speckle_publish"),
    ("load my speckle model", "speckle_load"),
]


def match_addon_recipe(request: str) -> GraphPlan | None:
    """The plan for a request that names an add-on (or something only an add-on does)."""
    hits = mentioned(_clean(request))
    for addon in hits:
        factory = ADDON_RECIPES.get(addon)
        if factory is not None:
            return factory(request)
    return None


def recipe_list() -> list[dict]:
    """What can be asked for, per add-on (for gh_addons / docs)."""
    out = []
    for addon, _factory in ADDON_RECIPES.items():
        out.append({"addon": addon, "title": ADDONS[addon].title,
                    "say": [phrase for phrase, _r in EXAMPLES
                            if mentioned(phrase) and mentioned(phrase)[0] == addon]})
    return out
