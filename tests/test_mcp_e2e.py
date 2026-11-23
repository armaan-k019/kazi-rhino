"""Claude's view: MCP client -> rhino-ai-mcp (subprocess) -> TCP -> real bridge script -> fake Rhino."""

import asyncio
import importlib.util
import json
import os
import pathlib
import sys

import pytest

from fakes import dotnet

mcp = pytest.importorskip("mcp")
from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge" / "rhino_ai_bridge.py"


@pytest.fixture
def rhino():
    env = dotnet.install(commands=("Box", "SelPrev", "Loft", "BooleanUnion"))
    spec = importlib.util.spec_from_file_location("bridge_for_mcp", BRIDGE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    bridge = mod.Bridge(port=0)
    bridge.start()
    env.port = bridge.sock.getsockname()[1]
    yield env
    bridge.stop()
    dotnet.uninstall()


def call_tools(port, calls):
    async def go():
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "rhino_ai_mods.mcp_server"],
            env={**os.environ, "RHINO_AI_BRIDGE_PORT": str(port)})
        async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            names = {t.name for t in (await s.list_tools()).tools}
            out = []
            for name, args in calls:
                res = await s.call_tool(name, args)
                text = "".join(c.text for c in res.content if getattr(c, "text", None))
                out.append(json.loads(text) if text.strip().startswith(("{", "[")) else text)
            return names, out
    return asyncio.run(go())


def test_tools_listed_and_status(rhino):
    names, (status,) = call_tools(rhino.port, [("bridge_status", {})])
    assert {"gh_build", "gh_create_script", "voice_command", "gh_recipes"} <= names
    assert status["grasshopper_open"] is True


def test_gh_build_recipe_through_mcp(rhino):
    rhino.rhino.selected.append(rhino.rhino.make_object("Brep", "facade"))
    _, (res,) = call_tools(rhino.port, [("gh_build", {"title": "x", "code": "", "outputs": [],
                                                       "inputs": [], "recipe": "voronoi_facade"})])
    assert res["status"] == "built", res
    kinds = sorted(type(o).__name__ for o in rhino.gh.doc.Objects)
    assert kinds == ["Group", "ParamGeometry", "ScriptComponent", "Slider", "Slider", "Slider"]
    script = next(o for o in rhino.gh.doc.Objects if type(o).__name__ == "ScriptComponent")
    assert "voronoi_cells" in script.source
    assert [len(p.Sources) for p in script.Params.Input] == [1, 1, 1, 1]


def test_gh_build_custom_plan_and_voice_command(rhino):
    plan = {"title": "Fins", "code": "fins = []", "outputs": ["fins"], "summary": "fins",
            "inputs": [{"name": "count", "type": "integer", "min": 1, "max": 40, "value": 12},
                       {"name": "flip", "type": "bool", "value": True}]}
    _, (res, voice, voice_run) = call_tools(rhino.port, [
        ("gh_build", plan),
        ("voice_command", {"text": "select previous"}),
        ("voice_command", {"text": "boolean union", "run": True}),
    ])
    assert res["status"] == "built"
    assert voice["macro"] == "_SelPrev"
    assert voice_run["sent"]["typed"] is True
    assert rhino.app.keystrokes[-1] == ("_BooleanUnion", False)


def test_mcp_reports_bridge_down():
    _, (status,) = call_tools(1, [("bridge_status", {})])
    assert "Can't reach the Rhino bridge" in status["error"]
