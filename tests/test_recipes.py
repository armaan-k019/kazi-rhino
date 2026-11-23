"""Run the Grasshopper recipe scripts against a simulated RhinoCommon."""

import math
import random

import pytest

from fakes import rhinocommon as rc
from rhino_ai_mods.gh.recipes import match_recipe, stepped_massing, voronoi_facade
from rhino_ai_mods.gh.voronoi2d import polygon_area, shrink, subdivide, voronoi_cells


@pytest.fixture(autouse=True)
def fake_rhino():
    rc.install()
    yield
    rc.uninstall()


# -- pure voronoi ------------------------------------------------------------ #

@pytest.mark.parametrize("n", [2, 7, 60, 200])
def test_voronoi_cells_tile_the_rectangle(n):
    rnd = random.Random(n)
    sites = [(rnd.uniform(0, 12), rnd.uniform(0, 4)) for _ in range(n)]
    cells = voronoi_cells(sites, 12, 4)
    assert len(cells) == n
    assert math.isclose(sum(abs(polygon_area(c)) for c in cells), 48, rel_tol=1e-6)
    for (sx, sy), cell in zip(sites, cells):
        xs, ys = [p[0] for p in cell], [p[1] for p in cell]
        assert min(xs) - 1e-9 <= sx <= max(xs) + 1e-9 and min(ys) - 1e-9 <= sy <= max(ys) + 1e-9


def test_shrink_and_subdivide():
    sq = [(0, 0), (2, 0), (2, 2), (0, 2)]
    assert math.isclose(abs(polygon_area(shrink(sq, 0.5))), 1.0)
    assert len(subdivide(sq, 8)) == 32


# -- voronoi facade script ---------------------------------------------------- #

def run_voronoi(**over):
    plan = voronoi_facade("")
    inputs = {"facade": [rc.vertical_facade(30, 12)], "count": 40, "seed": 3, "frame": 0.2}
    inputs.update(over)
    return rc.run_script(plan.code, **inputs)


def test_voronoi_facade_makes_closed_cells_on_the_facade():
    env, msgs = run_voronoi()
    assert not msgs
    assert len(env["cells"]) == 40 and len(env["openings"]) == 40 and len(env["sites"]) == 40
    for c in env["cells"]:
        assert c.IsClosed
        # every vertex lies on the facade plane (y == 0) within its bounds
        assert all(abs(p.Y) < 1e-9 and -1e-9 <= p.X <= 30 + 1e-9 and -1e-9 <= p.Z <= 12 + 1e-9 for p in c.pts)


def test_voronoi_cells_cover_the_whole_facade():
    env, _ = run_voronoi(count=25)
    total = sum(abs(rc._signed_area([(p.X, p.Z) for p in c.pts[:-1]])) for c in env["cells"])
    assert math.isclose(total, 30 * 12, rel_tol=1e-6)


def test_voronoi_frame_zero_means_no_openings_and_seed_changes_layout():
    env, _ = run_voronoi(frame=0)
    assert env["openings"] == []
    a, _ = run_voronoi(seed=1)
    b, _ = run_voronoi(seed=2)
    assert [(p.X, p.Z) for p in a["sites"]] != [(p.X, p.Z) for p in b["sites"]]


def test_voronoi_warns_without_facade():
    env, msgs = run_voronoi(facade=[])
    assert env["cells"] == [] and msgs and "facade" in msgs[0][1]


def test_voronoi_accepts_a_bare_surface_and_a_single_item():
    face = rc.vertical_facade(10, 5).Faces[0]
    env, msgs = run_voronoi(facade=face, count=5)
    assert not msgs and len(env["cells"]) == 5


# -- stepped massing script --------------------------------------------------- #

def run_steps(clockwise=False, **over):
    plan = stepped_massing("")
    inputs = {"footprint": [rc.rectangle(0, 0, 40, 24, clockwise=clockwise)], "floors": 12,
              "floor_height": 3.5, "step_every": 3, "setback": 2.0}
    inputs.update(over)
    return rc.run_script(plan.code, **inputs)


@pytest.mark.parametrize("clockwise", [False, True])
def test_stepped_massing_tiers_slabs_and_terraces(clockwise):
    env, msgs = run_steps(clockwise=clockwise)
    assert not msgs
    masses, slabs, terraces = env["masses"], env["slabs"], env["terraces"]
    assert len(masses) == 4 and all(m.capped for m in masses)
    assert len(slabs) == 12
    assert [round(s.pts[0].Z, 6) for s in slabs] == [round(i * 3.5, 6) for i in range(12)]
    # each tier is inset by 2 on every side
    widths = [max(p.X for p in m.profile.pts) - min(p.X for p in m.profile.pts) for m in masses]
    assert widths == pytest.approx([40, 36, 32, 28])
    assert [m.height for m in masses] == pytest.approx([10.5] * 4)
    # terraces are the rings left by each setback
    assert len(terraces) == 3
    assert terraces[0]._area == pytest.approx(40 * 24 - 36 * 20)


def test_stepped_massing_partial_top_tier_and_runaway_setback():
    env, _ = run_steps(floors=10)
    assert [m.height for m in env["masses"]] == pytest.approx([10.5, 10.5, 10.5, 3.5])
    env, msgs = run_steps(setback=7)
    assert len(env["masses"]) == 2 and any("consumed" in m[1] for m in msgs)


def test_stepped_massing_needs_closed_footprint():
    open_crv = rc.Curve([rc.Point3d(0, 0, 0), rc.Point3d(5, 0, 0)])
    env, msgs = run_steps(footprint=[open_crv])
    assert env["masses"] == [] and msgs


# -- picking recipes from speech --------------------------------------------- #

@pytest.mark.parametrize("speech,recipe", [
    ("build me a voronoi script that attaches to a facade", "voronoi_facade"),
    ("make a veroni pattern on this wall", "voronoi_facade"),
    ("build a stepping condition that sets back every 4 floors", "stepped_massing"),
    ("make a terraced massing", "stepped_massing"),
])
def test_match_recipe(speech, recipe):
    assert match_recipe(speech).recipe == recipe


def test_speech_numbers_become_slider_values():
    plan = match_recipe("build a stepping massing with twenty floors, setback of 3 every four floors")
    vals = {i.name: i.value for i in plan.inputs}
    assert vals["floors"] == 20 and vals["step_every"] == 4 and vals["setback"] == 3
    plan = match_recipe("voronoi facade with 120 cells")
    assert {i.name: i.value for i in plan.inputs}["count"] == 120


def test_unknown_request_has_no_recipe():
    assert match_recipe("build a louvre system") is None
