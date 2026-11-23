"""Grasshopper definitions as data ("plans"), plus hand-written recipes for common asks.

A plan is one script component plus the inputs that feed it:

* geometry inputs taken from what is selected in Rhino ("the facade"),
* number sliders / toggles for every parameter you might want to tweak.

The builder turns a plan into components on the canvas and wires them up. Recipes are used
directly when no model is configured, and as the tested starting point the model adapts.
"""

from __future__ import annotations

from . import facade_recipes as fr
from .plan import _HELPERS, Input, Plan, _number  # noqa: F401  (re-exported)
from .voronoi2d import VORONOI_SRC


# --------------------------------------------------------------------------- #
# Voronoi facade
# --------------------------------------------------------------------------- #

VORONOI_FACADE_CODE = '"""Voronoi cells mapped onto a facade surface. Built by kazi-rhino."""\nimport random\n' + _HELPERS + VORONOI_SRC + r'''

def largest_face(g):
    """Accept a Brep, Extrusion or Surface and return the surface to pattern."""
    if isinstance(g, rg.Extrusion):
        g = g.ToBrep()
    if isinstance(g, rg.Surface):
        return g
    if isinstance(g, rg.Brep) and g.Faces.Count:
        return max(g.Faces, key=lambda f: rg.AreaMassProperties.Compute(f).Area)
    return None


def main():
    srf = None
    for g in as_list(facade):
        srf = largest_face(g)
        if srf is not None:
            break
    if srf is None:
        warn("Select the facade surface in Rhino and connect it to 'facade'.")
        return [], [], []

    u, v = srf.Domain(0), srf.Domain(1)
    width = srf.IsoCurve(0, v.Mid).GetLength()
    height = srf.IsoCurve(1, u.Mid).GetLength()
    if width <= 0 or height <= 0:
        warn("Facade surface has zero size.")
        return [], [], []

    random.seed(int(seed))
    n = max(2, int(count))
    sites2d = [(random.uniform(0, width), random.uniform(0, height)) for _ in range(n)]

    def to_srf(p):
        return srf.PointAt(u.ParameterAt(p[0] / width), v.ParameterAt(p[1] / height))

    def to_curve(poly):
        pts = [to_srf(p) for p in subdivide(poly, 8)]
        pts.append(pts[0])
        return rg.PolylineCurve(pts)

    cells_out, openings_out = [], []
    for poly in voronoi_cells(sites2d, width, height):
        if len(poly) < 3:
            continue
        cells_out.append(to_curve(poly))
        if 0 < float(frame) < 1:
            openings_out.append(to_curve(shrink(poly, 1.0 - float(frame))))
    return cells_out, openings_out, [to_srf(p) for p in sites2d]


cells, openings, sites = main()
'''


def voronoi_facade(request: str = "") -> Plan:
    count = _number(request, r"(\d+)\s*(?:cells|openings|panels|points|pieces)", 60)
    return Plan(
        title="Voronoi facade",
        summary=(f"Splits the selected facade into {int(count)} Voronoi cells mapped onto the "
                 "surface, with inset openings for a frame."),
        inputs=[
            Input("facade", "geometry", "facade surface or polysurface", source="selection"),
            Input("count", "integer", "number of cells", 5, 400, count),
            Input("seed", "integer", "random seed (try different layouts)", 0, 100, 1),
            Input("frame", "number", "frame width as a fraction of each cell (0 = none)", 0, 0.5, 0.15),
        ],
        outputs=["cells", "openings", "sites"],
        code=VORONOI_FACADE_CODE,
        recipe="voronoi_facade",
    )


# --------------------------------------------------------------------------- #
# Stepped massing
# --------------------------------------------------------------------------- #

STEPPED_MASSING_CODE = '"""Stepped (terraced) massing from a footprint. Built by kazi-rhino."""\n' + _HELPERS + r'''

def outline(g):
    if isinstance(g, rg.Curve):
        return g
    if isinstance(g, rg.Extrusion):
        g = g.ToBrep()
    if isinstance(g, rg.Brep) and g.Faces.Count:
        face = min(g.Faces, key=lambda f: f.PointAt(f.Domain(0).Mid, f.Domain(1).Mid).Z)
        return face.OuterLoop.To3dCurve()
    return None


def area(c):
    amp = rg.AreaMassProperties.Compute(c)
    return amp.Area if amp else 0.0


def inset(crv, plane, d):
    """Offset a closed curve inward by d (works for either curve direction)."""
    if d <= 0:
        return crv
    a0 = area(crv)
    for sign in (1, -1):
        res = crv.Offset(plane, sign * d, TOL, rg.CurveOffsetCornerStyle.Sharp)
        if res and len(res) == 1 and res[0].IsClosed and 0 < area(res[0]) < a0:
            return res[0]
    return None


def moved(crv, z):
    c = crv.DuplicateCurve()
    c.Translate(rg.Vector3d(0, 0, z))
    return c


def main():
    crv = None
    for g in as_list(footprint):
        crv = outline(g)
        if crv is not None:
            break
    if crv is None or not crv.IsClosed:
        warn("Select a closed footprint curve (or a slab) in Rhino and connect it to 'footprint'.")
        return [], [], []
    ok, plane = crv.TryGetPlane(TOL)
    if not ok:
        warn("Footprint must be planar.")
        return [], [], []

    floors_n, every = max(1, int(floors)), max(1, int(step_every))
    h = float(floor_height)
    masses, slabs, terraces = [], [], []
    prev = None
    tier = 0
    while tier * every < floors_n:
        c = inset(crv, plane, tier * float(setback))
        if c is None:
            warn("Setback consumed the footprint after %d tiers." % tier)
            break
        start = tier * every
        n = min(every, floors_n - start)
        base = moved(c, start * h)
        ext = rg.Surface.CreateExtrusion(base, rg.Vector3d(0, 0, n * h))
        if ext is not None:
            brep = ext.ToBrep()
            capped = brep.CapPlanarHoles(TOL)
            masses.append(capped or brep)
        for k in range(n):
            slabs.append(moved(c, (start + k) * h))
        if prev is not None:
            ring = rg.Brep.CreatePlanarBreps([moved(prev, start * h), base], TOL)
            if ring:
                terraces.extend(ring)
        prev = c
        tier += 1
    return masses, slabs, terraces


masses, slabs, terraces = main()
'''


def stepped_massing(request: str = "") -> Plan:
    floors = _number(request, r"(\d+)\s*(?:floors|storeys|stories|levels)", 12)
    every = _number(request, r"every\s*(\d+)", 3)
    setback = _number(request, r"(\d+(?:\.\d+)?)\s*(?:m|meters?|metres?|units|feet|ft)?\s*setbacks?", 2.0)
    setback = _number(request, r"setbacks?\s*(?:of)?\s*(\d+(?:\.\d+)?)", setback)
    return Plan(
        title="Stepped massing",
        summary=(f"Extrudes the selected footprint {int(floors)} floors, stepping in by "
                 f"{setback:g} every {int(every)} floors, with terraces on each setback."),
        inputs=[
            Input("footprint", "geometry", "closed planar footprint curve or slab", source="selection"),
            Input("floors", "integer", "number of floors", 1, 80, floors),
            Input("floor_height", "number", "floor-to-floor height", 2.5, 6.0, 3.5),
            Input("step_every", "integer", "floors per tier", 1, 20, every),
            Input("setback", "number", "setback per tier", 0, 10, setback),
        ],
        outputs=["masses", "slabs", "terraces"],
        code=STEPPED_MASSING_CODE,
        recipe="stepped_massing",
    )


def _recipes() -> dict:
    # Order matters: the first recipe whose keyword appears in the request wins, so specific
    # patterns come before generic words like "panels".
    return {
        "voronoi_facade": (voronoi_facade, ("voronoi", "veroni", "voroni", "varanoi", "cellular")),
        "attractor_openings": (fr.attractor_openings, ("attractor", "perforat", "openings that",
                                                       "holes that", "gradient of openings")),
        "diagrid": (fr.diagrid, ("diagrid", "diagonal grid", "dia grid", "diamond grid", "lattice")),
        "fins": (fr.fins, ("fins", "fin ", "louvre", "louver", "louvers", "brise", "blades", "slats")),
        "stepped_massing": (stepped_massing, ("stepping", "stepped", "step back", "setback",
                                              "set back", "terrace", "terraced", "ziggurat", "tiered")),
        "panels": (fr.panels, ("panel", "panelise", "panelize", "cladding", "tiles", "tiling")),
    }


def match_recipe(request: str) -> Plan | None:
    from ..voice.rules import words_to_numbers  # noqa: PLC0415

    request = words_to_numbers(request.lower())
    low = request
    for factory, words in RECIPES.values():  # noqa: B007
        if any(w in low for w in words):
            return factory(request)
    return None


RECIPES = _recipes()
