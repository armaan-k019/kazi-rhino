"""A tiny stand-in for RhinoCommon + Grasshopper so recipe scripts can run outside Rhino.

Only what the recipes use is implemented, with real geometry math for planar polygons and
rectangular surfaces. It checks the scripts' logic (counts, areas, tiers), not RhinoCommon.
"""

from __future__ import annotations

import math
import sys
import types


class Point3d:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.X, self.Y, self.Z = float(x), float(y), float(z)

    def __add__(self, v):
        return Point3d(self.X + v.X, self.Y + v.Y, self.Z + v.Z)

    def __repr__(self):
        return f"Point3d({self.X:.3f},{self.Y:.3f},{self.Z:.3f})"


class Vector3d(Point3d):
    def __mul__(self, k):
        return Vector3d(self.X * k, self.Y * k, self.Z * k)


class Interval:
    def __init__(self, t0, t1):
        self.T0, self.T1 = float(t0), float(t1)

    @property
    def Mid(self):
        return (self.T0 + self.T1) / 2

    def ParameterAt(self, t):
        return self.T0 + t * (self.T1 - self.T0)


class Plane:
    WorldXY = None


class CurveOffsetCornerStyle:
    Sharp = "Sharp"


class GeometryBase:
    pass


class Curve(GeometryBase):
    """Closed or open polyline; closed means last point == first point."""

    def __init__(self, pts):
        self.pts = [Point3d(p.X, p.Y, p.Z) for p in pts]

    @property
    def IsClosed(self):
        a, b = self.pts[0], self.pts[-1]
        return len(self.pts) > 3 and abs(a.X - b.X) + abs(a.Y - b.Y) + abs(a.Z - b.Z) < 1e-9

    @property
    def PointAtStart(self):
        return self.pts[0]

    def GetLength(self):
        return sum(math.dist((a.X, a.Y, a.Z), (b.X, b.Y, b.Z)) for a, b in zip(self.pts, self.pts[1:]))

    def DuplicateCurve(self):
        return type(self)(self.pts)

    def Translate(self, v):
        self.pts = [p + v for p in self.pts]
        return True

    def TryGetPlane(self, tol=0.01):
        zs = {round(p.Z, 9) for p in self.pts}
        return (len(zs) == 1, Plane())

    def _ring(self):
        return [(p.X, p.Y) for p in self.pts[:-1]]

    def Offset(self, plane, distance, tol, style):
        """Positive = outward for a counter-clockwise polygon (sign flips for clockwise)."""
        ring = self._ring()
        n = len(ring)
        sa = _signed_area(ring)
        d = distance if sa > 0 else -distance
        lines = []
        for i in range(n):
            (x0, y0), (x1, y1) = ring[i], ring[(i + 1) % n]
            ex, ey = x1 - x0, y1 - y0
            ln = math.hypot(ex, ey)
            nx, ny = ey / ln, -ex / ln  # right-hand normal = outward for CCW
            lines.append(((x0 + nx * d, y0 + ny * d), (ex, ey)))
        out = []
        for i in range(n):
            (p, r), (q, s) = lines[i - 1], lines[i]
            den = r[0] * s[1] - r[1] * s[0]
            t = ((q[0] - p[0]) * s[1] - (q[1] - p[1]) * s[0]) / den
            out.append((p[0] + t * r[0], p[1] + t * r[1]))
        if _signed_area(out) * sa <= 0:  # polygon collapsed / inverted
            return []
        z = self.pts[0].Z
        pts = [Point3d(x, y, z) for x, y in out]
        return [PolylineCurve(pts + [pts[0]])]


class PolylineCurve(Curve):
    pass


def _signed_area(ring):
    return sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1])) / 2


class Surface(GeometryBase):
    """Planar rectangle: origin + u-axis * [0, w] + v-axis * [0, h]."""

    def __init__(self, origin, uvec, vvec, w, h):
        self.o, self.u, self.v, self.w, self.h = origin, uvec, vvec, float(w), float(h)

    def Domain(self, direction):
        return Interval(0, self.w) if direction == 0 else Interval(0, self.h)

    def PointAt(self, s, t):
        return self.o + self.u * s + self.v * t

    def NormalAt(self, s, t):
        u, v = self.u, self.v
        return Vector3d(u.Y * v.Z - u.Z * v.Y, u.Z * v.X - u.X * v.Z, u.X * v.Y - u.Y * v.X)

    def IsoCurve(self, direction, c):
        if direction == 0:
            return Curve([self.PointAt(0, c), self.PointAt(self.w, c)])
        return Curve([self.PointAt(c, 0), self.PointAt(c, self.h)])

    @staticmethod
    def CreateExtrusion(profile, vec):
        return _Extrusion(profile, vec)

    def ToBrep(self):
        return Brep([self])


class BrepFace(Surface):
    pass


class CurvedFace(BrepFace):
    """A vertical cylinder segment: s runs along an arc of `radius` through `angle` radians."""

    def __init__(self, radius, angle, h):
        self.r, self.a = float(radius), float(angle)
        super().__init__(Point3d(), Vector3d(1, 0, 0), Vector3d(0, 0, 1), self.r * self.a, h)

    def PointAt(self, s, t):
        th = s / self.r
        return Point3d(self.r * math.cos(th), self.r * math.sin(th), t)

    def NormalAt(self, s, t):
        th = s / self.r
        return Vector3d(math.cos(th), math.sin(th), 0)

    def IsoCurve(self, direction, c):
        if direction == 0:
            return Curve([self.PointAt(self.w * k / 400, c) for k in range(401)])
        return Curve([self.PointAt(c, 0), self.PointAt(c, self.h)])


class PipeCapMode:
    None_, Flat, Round = 0, 1, 2


class NurbsSurface(GeometryBase):
    """Ruled surface between two polylines (only what the recipes read)."""

    def __init__(self, a, b):
        self.a, self.b = a, b

    @staticmethod
    def CreateRuledSurface(a, b):
        return NurbsSurface(a, b)

    def ToBrep(self):
        return Brep([], "ruled", profile=self)


class _List(list):
    @property
    def Count(self):
        return len(self)


class Brep(GeometryBase):
    def __init__(self, faces, kind="surface", area=None, profile=None, height=None):
        self.Faces = _List(faces)
        self.kind, self._area, self.profile, self.height = kind, area, profile, height
        self.capped = False

    def CapPlanarHoles(self, tol):
        b = Brep(self.Faces, self.kind, self._area, self.profile, self.height)
        b.capped = True
        return b

    @staticmethod
    def CreateFromCornerPoints(a, b, c, d, tol):
        b_ = Brep([], "quad")
        b_.corners = [a, b, c, d]
        return b_

    @staticmethod
    def CreatePipe(rail, radius, local_blending, cap, fit_rail, abs_tol, ang_tol):
        b_ = Brep([], "pipe", profile=rail)
        b_.radius, b_.cap = radius, cap
        return [b_]

    @staticmethod
    def CreatePlanarBreps(curves, tol):
        curves = list(curves)
        areas = sorted((abs(_signed_area(c._ring())) for c in curves), reverse=True)
        return [Brep([], "planar", areas[0] - sum(areas[1:]))]


class _Extrusion:
    def __init__(self, profile, vec):
        self.profile, self.vec = profile, vec

    def ToBrep(self):
        return Brep([], "extrusion", profile=self.profile, height=self.vec.Z)


class Extrusion(GeometryBase):
    pass


class AreaMassProperties:
    def __init__(self, area):
        self.Area = area

    @staticmethod
    def Compute(g):
        if isinstance(g, Surface):
            return AreaMassProperties(g.w * g.h)
        if isinstance(g, Curve) and g.IsClosed:
            return AreaMassProperties(abs(_signed_area(g._ring())))
        return None


def rectangle(x0, y0, x1, y1, z=0.0, clockwise=False):
    pts = [Point3d(x0, y0, z), Point3d(x1, y0, z), Point3d(x1, y1, z), Point3d(x0, y1, z)]
    if clockwise:
        pts.reverse()
    return PolylineCurve(pts + [pts[0]])


def vertical_facade(width, height):
    """A facade in the XZ plane as a single-face Brep."""
    face = BrepFace(Point3d(0, 0, 0), Vector3d(1, 0, 0), Vector3d(0, 0, 1), width, height)
    return Brep([face])


class _Messages:
    def __init__(self):
        self.messages = []

    def AddRuntimeMessage(self, level, text):
        self.messages.append((level, text))


def install():
    """Put fake Rhino / Rhino.Geometry / Grasshopper modules in sys.modules."""
    geom = types.ModuleType("Rhino.Geometry")
    for name, obj in dict(globals()).items():
        if isinstance(obj, type) and not name.startswith("_"):
            setattr(geom, name, obj)
    rhino = types.ModuleType("Rhino")
    rhino.Geometry = geom
    rhino.RhinoDoc = types.SimpleNamespace(ActiveDoc=types.SimpleNamespace(ModelAbsoluteTolerance=0.001))
    gh = types.ModuleType("Grasshopper")
    gh.Kernel = types.SimpleNamespace(GH_RuntimeMessageLevel=types.SimpleNamespace(
        Warning="warning", Error="error", Remark="remark"))
    sys.modules.update({"Rhino": rhino, "Rhino.Geometry": geom, "Grasshopper": gh})
    return rhino


def uninstall():
    for name in ("Rhino", "Rhino.Geometry", "Grasshopper"):
        sys.modules.pop(name, None)


def run_script(code: str, **inputs):
    """Execute a Grasshopper script body with the given inputs; returns (globals, messages)."""
    ghenv = types.SimpleNamespace(Component=_Messages())
    env = {"__name__": "__gh__", "ghenv": ghenv, **inputs}
    exec(compile(code, "<gh-script>", "exec"), env)  # noqa: S102
    return env, ghenv.Component.messages
