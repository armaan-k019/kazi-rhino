"""Facade recipes: attractor openings, fins / louvres, panels, diagrid.

All four work on any facade you select (plane, curved surface, or the biggest face of a
polysurface). They share a small "facade map" that turns 0-1 facade coordinates (s along the
width, t up the height) into points and normals on the surface, so a flat wall and a curved
one behave the same.
"""

from __future__ import annotations

import re

from .plan import _HELPERS, Input, Plan, _number

_FACADE = _HELPERS + r'''
import math


def pt(x, y, z):
    return rg.Point3d(x, y, z)


def add(p, v, k=1.0):
    return pt(p.X + v[0] * k, p.Y + v[1] * k, p.Z + v[2] * k)


def unit(v):
    n = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2) or 1.0
    return (v[0] / n, v[1] / n, v[2] / n)


def rotate(v, axis, deg):
    """Rotate vector v about unit axis by deg degrees (Rodrigues)."""
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    kx, ky, kz = axis
    dot = kx * v[0] + ky * v[1] + kz * v[2]
    cross = (ky * v[2] - kz * v[1], kz * v[0] - kx * v[2], kx * v[1] - ky * v[0])
    return tuple(v[i] * c + cross[i] * s + axis[i] * dot * (1 - c) for i in range(3))


def facade_surface(geos):
    for g in as_list(geos):
        if isinstance(g, rg.Extrusion):
            g = g.ToBrep()
        if isinstance(g, rg.Surface):
            return g
        if isinstance(g, rg.Brep) and g.Faces.Count:
            return max(g.Faces, key=lambda f: rg.AreaMassProperties.Compute(f).Area)
    return None


class Facade(object):
    """0-1 facade coordinates (s across, t up) -> points, normals and curves on the surface."""

    def __init__(self, srf, flip=False):
        self.srf = srf
        self.u, self.v = srf.Domain(0), srf.Domain(1)
        self.width = srf.IsoCurve(0, self.v.Mid).GetLength()
        self.height = srf.IsoCurve(1, self.u.Mid).GetLength()
        self.sign = -1.0 if flip else 1.0

    def point(self, s, t):
        return self.srf.PointAt(self.u.ParameterAt(s), self.v.ParameterAt(t))

    def normal(self, s, t):
        n = self.srf.NormalAt(self.u.ParameterAt(s), self.v.ParameterAt(t))
        return unit((n.X * self.sign, n.Y * self.sign, n.Z * self.sign))

    def tangent(self, s0, t0, s1, t1):
        a, b = self.point(s0, t0), self.point(s1, t1)
        return unit((b.X - a.X, b.Y - a.Y, b.Z - a.Z))

    def path(self, pts01, closed=False, steps=8):
        """Polyline through 0-1 points, subdivided so it follows a curved facade."""
        ring = list(pts01) + ([pts01[0]] if closed else [])
        out = []
        for (s0, t0), (s1, t1) in zip(ring, ring[1:]):
            for k in range(steps):
                f = float(k) / steps
                out.append(self.point(s0 + (s1 - s0) * f, t0 + (t1 - t0) * f))
        out.append(out[0] if closed else self.point(*ring[-1]))
        return out

    def curve(self, pts01, closed=False, steps=8):
        return rg.PolylineCurve(self.path(pts01, closed, steps))


def open_facade(geos, flip=False):
    srf = facade_surface(geos)
    if srf is None:
        warn("Select the facade surface in Rhino and connect it to 'facade'.")
        return None
    f = Facade(srf, flip)
    if f.width <= 0 or f.height <= 0:
        warn("Facade surface has zero size.")
        return None
    return f
'''


# --------------------------------------------------------------------------- #
# Attractor openings
# --------------------------------------------------------------------------- #

ATTRACTOR_CODE = '"""Grid of openings that grow (or shrink) toward an attractor. Built by kazi-rhino."""\n' + _FACADE + r'''

def main():
    f = open_facade(facade)
    if f is None:
        return [], [], []
    cols, rows_n = max(1, int(columns)), max(1, int(rows))
    cw, ch = f.width / cols, f.height / rows_n
    diag = math.hypot(f.width, f.height)
    reach = max(1e-6, float(falloff)) * diag
    lo, hi = sorted((float(min_size), float(max_size)))
    n_sides = max(3, int(sides))
    ax, ay = float(attractor_x) * f.width, float(attractor_y) * f.height
    out, sizes, centers = [], [], []
    for j in range(rows_n):
        for i in range(cols):
            cx, cy = (i + 0.5) * cw, (j + 0.5) * ch
            k = min(1.0, math.hypot(cx - ax, cy - ay) / reach)   # 0 at the attractor, 1 far away
            if invert:
                k = 1.0 - k
            size = hi + (lo - hi) * k                              # fraction of the cell
            r = 0.5 * size * min(cw, ch)
            centers.append(f.point(cx / f.width, cy / f.height))
            sizes.append(size)
            if r <= 1e-6:
                continue
            poly = []
            for m in range(n_sides):
                a = 2 * math.pi * m / n_sides + (math.pi / 4 if n_sides == 4 else 0)
                poly.append(((cx + r * math.cos(a)) / f.width, (cy + r * math.sin(a)) / f.height))
            out.append(f.curve(poly, closed=True, steps=2))
    return out, sizes, centers


openings, sizes, centers = main()
'''


def attractor_openings(request: str = "") -> Plan:
    cols, rows = _grid(request, 12, 6)
    sides = 4 if re.search(r"\bsquares?\b|\brectang", request.lower()) else 24
    invert = bool(re.search(r"small(?:er)? near|shrink|smaller toward|smaller close", request.lower()))
    return Plan(
        title="Attractor openings",
        summary=(f"A {cols} x {rows} grid of {'square' if sides == 4 else 'round'} openings on the "
                 f"selected facade that get {'smaller' if invert else 'bigger'} near an attractor point "
                 "you move with two sliders."),
        inputs=[
            Input("facade", "geometry", "facade surface or polysurface", source="selection"),
            Input("columns", "integer", "openings across", 1, 80, cols),
            Input("rows", "integer", "openings up", 1, 60, rows),
            Input("min_size", "number", "smallest opening, fraction of its cell", 0, 1, 0.15),
            Input("max_size", "number", "biggest opening, fraction of its cell", 0, 1, 0.85),
            Input("attractor_x", "number", "attractor across the facade (0 = left, 1 = right)", 0, 1, 0.3),
            Input("attractor_y", "number", "attractor up the facade (0 = bottom, 1 = top)", 0, 1, 0.6),
            Input("falloff", "number", "how far the attractor reaches, fraction of the facade", 0.05, 1.5, 0.6),
            Input("sides", "integer", "polygon sides (4 = square, 24 = round)", 3, 48, sides),
            Input("invert", "bool", "small near the attractor instead of big", value=invert),
        ],
        outputs=["openings", "sizes", "centers"],
        code=ATTRACTOR_CODE,
        recipe="attractor_openings",
    )


# --------------------------------------------------------------------------- #
# Fins / louvres
# --------------------------------------------------------------------------- #

FINS_CODE = '"""Fins (vertical) or louvres (horizontal) standing off a facade. Built by kazi-rhino."""\n' + _FACADE + r'''

def main():
    f = open_facade(facade, flip)
    if f is None:
        return [], []
    n = max(1, int(count))
    fins_out, axes = [], []
    for i in range(n):
        c = (i + 0.5) / n
        # vertical fins run up the facade at s = c; horizontal louvres run across at t = c
        ends = [(c, 0.0), (c, 1.0)] if not horizontal else [(0.0, c), (1.0, c)]
        base = f.path(ends, steps=8)
        twist = float(rotation) + float(twist_range) * (c - 0.5) * 2   # degrees, varies across the run
        edge = []
        for k, p in enumerate(base):
            g = k / float(len(base) - 1)
            s, t = (c, g) if not horizontal else (g, c)
            s, t = min(max(s, 1e-6), 1 - 1e-6), min(max(t, 1e-6), 1 - 1e-6)
            axis = f.tangent(*(ends[0] + ends[1]))
            d = rotate(f.normal(s, t), axis, twist)
            edge.append(add(p, d, float(depth)))
        a, b = rg.PolylineCurve(base), rg.PolylineCurve(edge)
        srf = rg.NurbsSurface.CreateRuledSurface(a, b)
        if srf is not None:
            fins_out.append(srf.ToBrep())
        axes.append(a)
    return fins_out, axes


fins, axes = main()
'''


def fins(request: str = "") -> Plan:
    low = request.lower()
    horizontal = bool(re.search(r"louv|horizontal|brise|shade|shading", low)) and "vertical" not in low
    count = _number(low, r"(\d+)\s*(?:vertical\s+|horizontal\s+)?(?:fins|louvres|louvers|blades|slats)", 12 if horizontal else 20)
    depth = _number(low, r"(\d+(?:\.\d+)?)\s*(?:m|metres?|meters?|units)?\s*deep", 0.6)
    depth = _number(low, r"depth\s*(?:of)?\s*(\d+(?:\.\d+)?)", depth)
    rotation = _number(low, r"(-?\d+)\s*(?:degrees?|deg)", 0)
    kind = "louvres" if horizontal else "fins"
    return Plan(
        title="Louvres" if horizontal else "Fins",
        summary=(f"{int(count)} {'horizontal' if horizontal else 'vertical'} {kind}, {depth:g} deep, "
                 "standing off the selected facade, with rotation and a twist that varies across them."),
        inputs=[
            Input("facade", "geometry", "facade surface or polysurface", source="selection"),
            Input("count", "integer", f"number of {kind}", 1, 200, count),
            Input("depth", "number", f"how far the {kind} stick out", 0.05, 3, depth),
            Input("rotation", "number", "rotation from perpendicular, degrees", -90, 90, rotation),
            Input("twist_range", "number", "extra rotation from first to last, +/- degrees", 0, 90, 0),
            Input("horizontal", "bool", "louvres (across) instead of fins (up)", value=horizontal),
            Input("flip", "bool", "put them on the other side of the facade", value=False),
        ],
        outputs=["fins", "axes"],
        code=FINS_CODE,
        recipe="fins",
    )


# --------------------------------------------------------------------------- #
# Panels
# --------------------------------------------------------------------------- #

PANELS_CODE = '"""Facade panelisation with joints and optional running bond. Built by kazi-rhino."""\n' + _FACADE + r'''

def main():
    f = open_facade(facade)
    if f is None:
        return [], [], []
    cols, rows_n = max(1, int(columns)), max(1, int(rows))
    cw, ch = f.width / cols, f.height / rows_n
    g = max(0.0, min(float(gap), 0.9 * min(cw, ch)))
    panels_out, outlines, centers = [], [], []
    for j in range(rows_n):
        shift = 0.5 * cw if (stagger and j % 2) else 0.0
        cuts = [shift + i * cw for i in range(cols + 1)]
        edges = sorted(set([0.0, f.width] + [x for x in cuts if 1e-9 < x < f.width - 1e-9]))
        for x0, x1 in zip(edges, edges[1:]):
            y0, y1 = j * ch, (j + 1) * ch
            a, b = x0 + g / 2, x1 - g / 2
            c, d = y0 + g / 2, y1 - g / 2
            if b - a <= 1e-6 or d - c <= 1e-6:
                continue
            quad = [(a / f.width, c / f.height), (b / f.width, c / f.height),
                    (b / f.width, d / f.height), (a / f.width, d / f.height)]
            corners = [f.point(*q) for q in quad]
            brep = rg.Brep.CreateFromCornerPoints(corners[0], corners[1], corners[2], corners[3], TOL)
            if brep is not None:
                panels_out.append(brep)
            outlines.append(f.curve(quad, closed=True, steps=4))
            centers.append(f.point((a + b) / 2 / f.width, (c + d) / 2 / f.height))
    return panels_out, outlines, centers


panels, outlines, centers = main()
'''


def panels(request: str = "") -> Plan:
    cols, rows = _grid(request, 10, 8)
    low = request.lower()
    stagger = bool(re.search(r"stagger|running bond|brick|offset rows", low))
    gap = _number(low, r"(\d+(?:\.\d+)?)\s*(?:m|mm|metres?|meters?|units)?\s*(?:gaps?|joints?)", 0.02)
    if re.search(r"\d\s*mm", low):
        gap = gap / 1000.0
    return Plan(
        title="Facade panels",
        summary=(f"Splits the selected facade into a {cols} x {rows} grid of flat panels with "
                 f"{gap:g} joints{', staggered like brickwork' if stagger else ''}."),
        inputs=[
            Input("facade", "geometry", "facade surface or polysurface", source="selection"),
            Input("columns", "integer", "panels across", 1, 120, cols),
            Input("rows", "integer", "panels up", 1, 80, rows),
            Input("gap", "number", "joint width between panels", 0, 0.5, gap),
            Input("stagger", "bool", "offset every other row by half a panel", value=stagger),
        ],
        outputs=["panels", "outlines", "centers"],
        code=PANELS_CODE,
        recipe="panels",
    )


# --------------------------------------------------------------------------- #
# Diagrid
# --------------------------------------------------------------------------- #

DIAGRID_CODE = '"""Diagrid structure on a facade or tower skin. Built by kazi-rhino."""\n' + _FACADE + r'''

def main():
    f = open_facade(facade)
    if f is None:
        return [], [], [], []
    nb, nl = max(1, int(bays)), max(1, int(levels))
    nodes = {}
    for j in range(nl + 1):
        for i in range(nb + 1):
            if (i + j) % 2 == 0:
                nodes[(i, j)] = (float(i) / nb, float(j) / nl)
    members_out = []
    for (i, j), a in sorted(nodes.items()):
        for di, dj in ((1, 1), (1, -1)):
            b = nodes.get((i + di, j + dj))
            if b is not None:
                members_out.append(f.curve([a, b], steps=8))
    rings_out = []
    if ring_beams:
        for j in range(nl + 1):
            rings_out.append(f.curve([(0.0, float(j) / nl), (1.0, float(j) / nl)], steps=4 * nb))
    pipes = []
    if float(radius) > 0:
        for c in members_out + rings_out:
            res = rg.Brep.CreatePipe(c, float(radius), False, rg.PipeCapMode.Flat, True, TOL, 0.01)
            if res:
                pipes.extend(res)
    return members_out, rings_out, [f.point(*p) for _, p in sorted(nodes.items())], pipes


members, rings, nodes, structure = main()
'''


def diagrid(request: str = "") -> Plan:
    low = request.lower()
    bays = _number(low, r"(\d+)\s*(?:bays|diamonds|modules)\b", 8)
    levels = _number(low, r"(\d+)\s*(?:levels|floors|storeys|stories|rows)", 6)
    radius = _number(low, r"(\d+(?:\.\d+)?)\s*(?:m|metres?|meters?|units)?\s*radius", 0.15)
    radius = _number(low, r"radius\s*(?:of)?\s*(\d+(?:\.\d+)?)", radius)
    return Plan(
        title="Diagrid",
        summary=(f"A diagrid on the selected facade, {int(bays)} bays across and {int(levels)} levels "
                 f"up, with ring beams and members piped at radius {radius:g}."),
        inputs=[
            Input("facade", "geometry", "facade or tower surface", source="selection"),
            Input("bays", "integer", "diamonds across (even numbers close around a tower)", 1, 60, bays),
            Input("levels", "integer", "node levels up", 1, 60, levels),
            Input("radius", "number", "member radius (0 = curves only)", 0, 1, radius),
            Input("ring_beams", "bool", "horizontal beams at each node level", value=True),
        ],
        outputs=["members", "rings", "nodes", "structure"],
        code=DIAGRID_CODE,
        recipe="diagrid",
    )


def _grid(text: str, cols: int, rows: int) -> tuple[int, int]:
    m = re.search(r"(\d+)\s*(?:by|x|×)\s*(\d+)", text.lower())
    if m:
        return int(m.group(1)), int(m.group(2))
    cols = int(_number(text, r"(\d+)\s*(?:columns|cols|across)", cols))
    rows = int(_number(text, r"(\d+)\s*(?:rows|up|high)", rows))
    return cols, rows
