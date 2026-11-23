"""Kazi* Rhino commands (status, undo build, bake), slider edits, and the in-Rhino installer."""

import contextlib
import importlib.util
import io
import pathlib
import runpy

import pytest

from fakes import dotnet
from rhino_ai_mods.bridge_client import BridgeClient
from rhino_ai_mods.gh.builder import Builder
from rhino_ai_mods.gh.recipes import voronoi_facade

ROOT = pathlib.Path(__file__).resolve().parents[1] / "bridge"


@pytest.fixture
def rhino():
    env = dotnet.install(commands=("Box", "mcpstart"))
    spec = importlib.util.spec_from_file_location("bridge_kazi", ROOT / "rhino_ai_bridge.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.PORT = 0
    mod.main()
    bridge = env.sc.sticky["rhino_ai_mods_bridge"]
    env.client = BridgeClient(port=bridge.sock.getsockname()[1])
    env.rhino.selected.append(env.rhino.make_object("Brep", "facade"))
    yield env
    env.client.close()
    bridge.stop()
    dotnet.uninstall()


def build(env):
    return Builder(env.client, None, confirm=False).build(voronoi_facade("60 cells"))


def run_in_rhino(env, script):
    """Run a bridge/*.py script the way Rhino's ScriptEditor would: on the UI thread."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        env.app.run_on_ui(lambda: runpy.run_path(str(ROOT / script), run_name="__main__"))
    return out.getvalue()


def test_builds_are_recorded_with_sliders(rhino):
    res = build(rhino)
    builds = rhino.client.call("kazi_builds")["builds"]
    assert builds[-1]["title"] == "Voronoi facade" and builds[-1]["script"] == res.script
    assert sorted(builds[-1]["sliders"]) == ["count", "frame", "seed"]


def test_status_script(rhino):
    assert "nothing built yet" in run_in_rhino(rhino, "kazi_status.py")
    build(rhino)
    out = run_in_rhino(rhino, "kazi_status.py")
    assert "bridge running" in out and "-> Voronoi facade" in out and "count, frame, seed" in out


def test_undo_build_script_runs_on_ui_thread_without_deadlock(rhino):
    build(rhino)
    assert len(rhino.gh.doc.Objects) == 6
    run_in_rhino(rhino, "kazi_undo_build.py")
    assert rhino.gh.doc.Objects == []
    assert any("removed 'Voronoi facade'" in line for line in rhino.app.lines)
    assert "Nothing built" in run_in_rhino(rhino, "kazi_undo_build.py")


def test_undo_only_removes_the_last_build(rhino):
    build(rhino)
    build(rhino)
    rhino.client.call("kazi_undo_build")
    assert len(rhino.gh.doc.Objects) == 6 and len(rhino.client.call("kazi_builds")["builds"]) == 1


def test_bake_script_puts_outputs_on_layers(rhino):
    res = build(rhino)
    script = next(o for o in rhino.gh.doc.Objects if type(o).__name__ == "ScriptComponent")
    cells = next(p for p in script.Params.Output if p.NickName == "cells")
    cells.VolatileData.extend(["crv1", "crv2", "crv3"])
    run_in_rhino(rhino, "kazi_bake.py")
    layers = [layer.FullPath for layer in rhino.rhino.RhinoDoc.ActiveDoc.Layers]
    assert "kazi::Voronoi facade::cells" in layers and "kazi::Voronoi facade" in layers
    cell_layer = layers.index("kazi::Voronoi facade::cells")
    assert [g for g, li in rhino.rhino.added if li == cell_layer] == ["crv1", "crv2", "crv3"]
    assert rhino.rhino.undo == [("begin", "kazi bake"), ("end", 7)]
    assert res.script


def test_set_slider_widens_range(rhino):
    build(rhino)
    rhino.client.call("gh_set_slider", component="count", value=30)
    assert rhino.client.call("gh_get_slider", component="count")["value"] == 30
    r = rhino.client.call("gh_set_slider", component="count", value=900)
    assert r["value"] == 900 and r["max"] == 900


def test_install_in_rhino_adds_aliases(rhino):
    out = run_in_rhino(rhino, "install_in_rhino.py")
    aliases = rhino.rhino.ApplicationSettings.CommandAliasList.items
    assert set(aliases) == {"KaziStart", "KaziStop", "KaziStatus", "KaziUndoBuild", "KaziBake"}
    assert aliases["KaziStart"].startswith("_-mcpstart _Enter _-ScriptEditor _Run")
    assert str(ROOT / "kazi_bake.py") in aliases["KaziBake"]
    assert "Run these commands every time Rhino starts" in out
    run_in_rhino(rhino, "install_in_rhino.py")  # re-running updates instead of failing


def test_voice_edits_through_the_real_bridge_script(rhino):
    """Editor -> bridge script (fake .NET) -> slider and toggle objects actually change."""
    from rhino_ai_mods.gh.edits import Editor
    from rhino_ai_mods.gh.facade_recipes import fins

    Builder(rhino.client, None, confirm=False).build(fins("20 fins"))
    ed = Editor(rhino.client)
    assert ed.handle("more fins").changes[0].new == 25
    assert ed.handle("flip them").changes[0].new is True
    rec = rhino.client.call("kazi_builds")["builds"][-1]
    assert rhino.client.call("gh_get_slider", component=rec["sliders"]["count"])["value"] == 25
    assert rhino.client.call("gh_toggle", component=rec["toggles"]["flip"])["value"] is True
    ed.handle("undo")
    assert rhino.client.call("gh_toggle", component=rec["toggles"]["flip"])["value"] is False
    ed.handle("set depth to 5")   # beyond the slider max: range widens
    info = rhino.client.call("gh_get_slider", component=rec["sliders"]["depth"])
    assert info["value"] == 5 and info["max"] >= 5
    with pytest.raises(Exception, match="not a boolean toggle"):
        rhino.client.call("gh_toggle", component=rec["sliders"]["count"])


def test_model_code_edit_through_the_real_bridge_script(rhino):
    from rhino_ai_mods.gh.edits import Editor
    from rhino_ai_mods.gh.planner import Planner

    class LLM:
        prompts = []

        def complete(self, messages, max_tokens=96):
            self.prompts.append(messages[-1]["content"])
            return "```python\ncells, openings, sites = [], [], []\n```"

    res = build(rhino)
    llm = LLM()
    out = Editor(rhino.client, Planner(llm), confirm=False).handle("make the openings circular")
    assert out.status == "edited", out
    assert "(facade, count, seed, frame)" in llm.prompts[0] and "(cells, openings, sites)" in llm.prompts[0]
    code = rhino.client.call("gh_read_script", component=res.script)["code"]
    assert code.startswith("cells, openings, sites = [], [], []")
