"""Facade recipes (attractor openings, fins/louvres, panels, diagrid) in simulated RhinoCommon."""

import math

import pytest

from fakes import rhinocommon as rc
from rhino_ai_mods.gh import facade_recipes as fr
from rhino_ai_mods.gh.recipes import RECIPES, match_recipe


@pytest.fixture(autouse=True)
def fake_rhino():
    rc.install()
    yield
    rc.uninstall()


def flat():
    return [rc.vertical_facade(30, 12)]          # XZ plane, normal -Y


def curved():
    return [rc.Brep([rc.CurvedFace(20, math.pi / 2, 12)])]   # quarter cylinder, r=20


def run(plan, **inputs):
    defaults = {i.name: i.value for i in plan.inputs if i.type != "geometry"}
    defaults.update(inputs)
    return rc.run_script(plan.code, **defaults)


def area_xz(curve):
    return abs(rc._signed_area([(p.X, p.Z) for p in curve.pts[:-1]]))


# -- attractor openings ------------------------------------------------------- #

def test_attractor_openings_grow_toward_the_attractor():
    plan = fr.attractor_openings("")
    env, msgs = run(plan, facade=flat(), columns=10, rows=4, attractor_x=0.0, attractor_y=0.0,
                    sides=4, min_size=0.1, max_size=0.9, falloff=1.0, invert=False)
    assert not msgs
    ops, sizes = env["openings"], env["sizes"]
    assert len(ops) == 40 and len(sizes) == 40 and len(env["centers"]) == 40
    assert all(o.IsClosed for o in ops)
    # bottom-left cell (near the attractor) is bigger than top-right
    assert sizes[0] > sizes[-1]
    assert area_xz(ops[0]) > area_xz(ops[-1])
    # a square of size 0.9*cell side: cells are 3 x 3, so the opening is at most 2.7 wide
    xs = [p.X for p in ops[0].pts]
    assert max(xs) - min(xs) <= 2.7 + 1e-6
    # every opening stays inside its own cell (no overlaps)
    for o, c in zip(ops, env["centers"]):
        assert all(abs(p.X - c.X) <= 1.5 + 1e-6 and abs(p.Z - c.Z) <= 1.5 + 1e-6 for p in o.pts)


def test_attractor_invert_and_zero_size_skips():
    plan = fr.attractor_openings("")
    env, _ = run(plan, facade=flat(), columns=6, rows=2, attractor_x=0, attractor_y=0, invert=True,
                 falloff=1.0)
    assert env["sizes"][0] < env["sizes"][-1]
    env, _ = run(plan, facade=flat(), columns=6, rows=2, min_size=0, max_size=0)
    assert env["openings"] == [] and len(env["sizes"]) == 12


def test_attractor_on_curved_facade_lies_on_the_cylinder():
    env, msgs = run(fr.attractor_openings(""), facade=curved(), columns=8, rows=3)
    assert not msgs and len(env["openings"]) == 24
    for o in env["openings"]:
        assert all(abs(math.hypot(p.X, p.Y) - 20) < 1e-9 for p in o.pts)


def test_attractor_speech():
    p = fr.attractor_openings("square openings 20 by 8 smaller near the attractor")
    v = {i.name: i.value for i in p.inputs}
    assert (v["columns"], v["rows"], v["sides"], v["invert"]) == (20, 8, 4, True)


# -- fins / louvres ----------------------------------------------------------- #

def fin_depth(fin):
    a, b = fin.profile.a.pts, fin.profile.b.pts
    return [math.dist((p.X, p.Y, p.Z), (q.X, q.Y, q.Z)) for p, q in zip(a, b)]


def test_vertical_fins_stand_off_the_facade():
    plan = fr.fins("")
    env, msgs = run(plan, facade=flat(), count=10, depth=0.5)
    assert not msgs and len(env["fins"]) == 10 and len(env["axes"]) == 10
    for k, fin in enumerate(env["fins"]):
        assert fin_depth(fin) == pytest.approx([0.5] * len(fin.profile.a.pts))
        base, edge = fin.profile.a.pts, fin.profile.b.pts
        assert base[0].Z == pytest.approx(0) and base[-1].Z == pytest.approx(12)
        assert all(p.X == pytest.approx((k + 0.5) * 3) for p in base)     # evenly spaced
        assert all(q.Y == pytest.approx(-0.5) for q in edge)               # perpendicular, normal side


def test_fins_rotation_flip_and_twist():
    plan = fr.fins("")
    env, _ = run(plan, facade=flat(), count=1, depth=1.0, rotation=90)
    edge, base = env["fins"][0].profile.b.pts, env["fins"][0].profile.a.pts
    # rotated 90 degrees about the vertical axis: now lies in the facade plane
    assert all(abs(q.Y) < 1e-9 and abs(abs(q.X - p.X) - 1) < 1e-9 for p, q in zip(base, edge))
    env, _ = run(plan, facade=flat(), count=2, flip=True)
    assert all(q.Y > 0 for q in env["fins"][0].profile.b.pts)
    env, _ = run(plan, facade=flat(), count=3, twist_range=45)
    angles = []
    for fin in env["fins"]:
        p, q = fin.profile.a.pts[0], fin.profile.b.pts[0]
        angles.append(round(math.degrees(math.atan2(q.X - p.X, -(q.Y - p.Y)))))
    assert angles == [-30, 0, 30]


def test_horizontal_louvres_and_curved_facade():
    env, msgs = run(fr.fins("louvres"), facade=curved(), count=6, depth=0.4)
    assert not msgs and len(env["fins"]) == 6
    for k, fin in enumerate(env["fins"]):
        base, edge = fin.profile.a.pts, fin.profile.b.pts
        assert all(p.Z == pytest.approx((k + 0.5) * 2) for p in base)    # level louvres
        assert all(math.hypot(p.X, p.Y) == pytest.approx(20) for p in base)   # follow the curve
        assert all(math.hypot(q.X, q.Y) == pytest.approx(20.4) for q in edge)  # 0.4 outward


def test_fins_speech():
    p = fr.fins("make 30 vertical fins 0.8 deep rotated 15 degrees")
    v = {i.name: i.value for i in p.inputs}
    assert (v["count"], v["depth"], v["rotation"], v["horizontal"]) == (30, 0.8, 15, False)
    assert fr.fins("horizontal louvers").title == "Louvres"


# -- panels ------------------------------------------------------------------- #

def test_panels_grid_with_joints():
    env, msgs = run(fr.panels(""), facade=flat(), columns=10, rows=4, gap=0.1, stagger=False)
    assert not msgs and len(env["panels"]) == 40 and len(env["outlines"]) == 40
    q = env["panels"][0].corners
    assert (q[0].X, q[0].Z, q[2].X, q[2].Z) == pytest.approx((0.05, 0.05, 2.95, 2.95))
    total = sum(area_xz(o) for o in env["outlines"])
    assert total == pytest.approx(40 * 2.9 * 2.9)


def test_panels_stagger_running_bond():
    env, _ = run(fr.panels(""), facade=flat(), columns=10, rows=2, gap=0, stagger=True)
    # row 0: 10 full panels; row 1: half + 9 full + half
    assert len(env["panels"]) == 21
    widths = sorted(round(max(p.X for p in o.pts) - min(p.X for p in o.pts), 6) for o in env["outlines"])
    assert widths == [1.5, 1.5] + [3.0] * 19
    assert sum(area_xz(o) for o in env["outlines"]) == pytest.approx(30 * 12)


def test_panels_speech_mm_gap():
    v = {i.name: i.value for i in fr.panels("panelize the facade 12 x 6 with 20mm joints, brick bond").inputs}
    assert (v["columns"], v["rows"], v["gap"], v["stagger"]) == (12, 6, 0.02, True)


# -- diagrid ------------------------------------------------------------------- #

def test_diagrid_members_nodes_rings_and_pipes():
    env, msgs = run(fr.diagrid(""), facade=flat(), bays=4, levels=2, radius=0.2, ring_beams=True)
    assert not msgs
    # nodes where (i + j) is even on a 5 x 3 lattice
    assert len(env["nodes"]) == 8
    # each diamond edge once: up-right and down-right from every node that has a partner
    assert len(env["members"]) == 8
    assert len(env["rings"]) == 3
    assert len(env["structure"]) == 11 and all(b.radius == 0.2 for b in env["structure"])
    m = env["members"][0]
    assert m.pts[0].X == pytest.approx(0) and m.pts[-1].X == pytest.approx(7.5)
    assert {round(m.pts[-1].Z, 6) for m in env["members"]} <= {0, 6, 12}


def test_diagrid_curves_only_and_curved_facade():
    env, _ = run(fr.diagrid(""), facade=curved(), bays=6, levels=4, radius=0, ring_beams=False)
    assert env["structure"] == [] and env["rings"] == []
    for m in env["members"]:
        assert all(math.hypot(p.X, p.Y) == pytest.approx(20) for p in m.pts)


# -- all recipes --------------------------------------------------------------- #

@pytest.mark.parametrize("name", ["attractor_openings", "fins", "panels", "diagrid"])
def test_every_recipe_warns_without_a_facade(name):
    plan = RECIPES[name][0]("")
    env, msgs = run(plan, facade=[])
    assert msgs and "facade" in msgs[0][1]
    assert all(env[o] == [] for o in plan.outputs)


@pytest.mark.parametrize("name", sorted(RECIPES))
def test_every_recipe_runs_at_slider_extremes(name):
    """Min and max of every slider must solve without crashing."""
    plan = RECIPES[name][0]("")
    geo = [rc.rectangle(0, 0, 40, 24)] if name == "stepped_massing" else flat()
    key = next(i.name for i in plan.inputs if i.type == "geometry")
    for pick in ("min", "max"):
        vals = {i.name: getattr(i, pick) for i in plan.inputs if i.type in ("number", "integer")}
        env, msgs = run(plan, **{key: geo}, **vals)
        assert not [m for m in msgs if m[0] == "error"]


@pytest.mark.parametrize("speech,recipe", [
    ("build me an attractor point script for openings on this facade", "attractor_openings"),
    ("perforated facade that gets denser near the entrance", "attractor_openings"),
    ("add vertical fins along the facade", "fins"),
    ("make horizontal louvres on the south wall", "fins"),
    ("brise soleil please", "fins"),
    ("panelize this facade 12 by 6", "panels"),
    ("cladding grid with 20 mm joints", "panels"),
    ("put a diagrid on the tower", "diagrid"),
    ("voronoi panels on the facade", "voronoi_facade"),
    ("stepped massing with terraces", "stepped_massing"),
])
def test_match_new_recipes(speech, recipe):
    assert match_recipe(speech).recipe == recipe
