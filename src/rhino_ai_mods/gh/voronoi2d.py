"""Plain-Python 2D Voronoi cells, clipped to a rectangle.

The source lives in VORONOI_SRC so the exact same code can be pasted into a Grasshopper
script component (which can't import this package) and tested here.
"""

VORONOI_SRC = r'''
def _clip(poly, a, b, c):
    """Keep the part of polygon `poly` where a*x + b*y <= c (Sutherland-Hodgman, one edge)."""
    out = []
    n = len(poly)
    for i in range(n):
        p, q = poly[i], poly[(i + 1) % n]
        fp = a * p[0] + b * p[1] - c
        fq = a * q[0] + b * q[1] - c
        if fp <= 0:
            out.append(p)
        if (fp < 0 < fq) or (fq < 0 < fp):
            t = fp / (fp - fq)
            out.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
    return out


def voronoi_cells(sites, width, height):
    """One convex polygon (list of (x, y)) per site, clipped to [0, width] x [0, height]."""
    rect = [(0.0, 0.0), (width, 0.0), (width, height), (0.0, height)]
    cells = []
    for i, (sx, sy) in enumerate(sites):
        poly = rect
        for j, (tx, ty) in enumerate(sites):
            if i == j or not poly:
                continue
            a, b = tx - sx, ty - sy
            if a == 0 and b == 0:
                continue
            c = (tx * tx + ty * ty - sx * sx - sy * sy) / 2.0
            poly = _clip(poly, a, b, c)
        cells.append(poly)
    return cells


def polygon_area(poly):
    s = 0.0
    for i in range(len(poly)):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % len(poly)]
        s += x0 * y1 - x1 * y0
    return s / 2.0


def polygon_centroid(poly):
    a = polygon_area(poly)
    if abs(a) < 1e-12:
        n = float(len(poly))
        return (sum(p[0] for p in poly) / n, sum(p[1] for p in poly) / n)
    cx = cy = 0.0
    for i in range(len(poly)):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % len(poly)]
        f = x0 * y1 - x1 * y0
        cx += (x0 + x1) * f
        cy += (y0 + y1) * f
    return (cx / (6.0 * a), cy / (6.0 * a))


def shrink(poly, factor):
    """Scale a polygon about its centroid (factor 1 = unchanged, 0.8 = 80% size)."""
    cx, cy = polygon_centroid(poly)
    return [(cx + (x - cx) * factor, cy + (y - cy) * factor) for x, y in poly]


def subdivide(poly, n):
    """Insert n-1 points along each edge so the outline can follow a curved surface."""
    out = []
    for i in range(len(poly)):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % len(poly)]
        for k in range(n):
            t = k / float(n)
            out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
    return out
'''

exec(VORONOI_SRC, globals())  # noqa: S102  (defines the functions above for import/tests)
