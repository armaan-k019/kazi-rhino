"""MCP server that lets Claude author Grasshopper script components through the Rhino bridge.

It is meant to run next to rhinomcp (https://github.com/jingcheng-chen/rhinomcp), which already
covers geometry, sliders and general Grasshopper wiring. This server adds what rhinomcp lacks:
creating and editing Python 3 / C# script components, with their code, inputs and outputs, and
reading back their errors so Claude can fix its own scripts.
"""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from .bridge_client import BridgeClient, BridgeError
from .gh.builder import Builder
from .gh.recipes import RECIPES, Input, Plan
from .voice.rules import RuleMapper

INSTRUCTIONS = """\
Tools for Grasshopper script components in Rhino 8 (via the rhino-ai-mods bridge).

Workflow for a script:
1. gh_create_script with code + inputs + outputs. Inputs/outputs you name become the script's
   variables (Python: plain globals; outputs are assigned as variables, e.g. `a = ...`).
2. Read the returned `errors` / `messages`. If there are errors, fix with gh_update_script.
3. Feed it data: gh_add_component (e.g. "Number Slider", "Panel", "Point") then gh_connect.
4. gh_list / gh_read_script show current state; gh_solve recomputes and lists problems.

Python 3 script tips (Rhino 8): `import Rhino.Geometry as rg`; inputs arrive already converted
(set access "list" for lists); assign outputs by name. For C#, put logic in RunScript and use
the `out` params generated for each output name.
Components are referenced by GUID (preferred) or nickname.

Fastest way to a working, tweakable definition: gh_build with a plan (one script + sliders +
the Rhino selection as geometry input, all wired and grouped). gh_recipes lists tested plans
(voronoi facade, stepped massing) you can build directly or use as a starting point.
voice_command shows how spoken words map to Rhino commands.
"""

mcp = FastMCP("rhino-ai-mods", instructions=INSTRUCTIONS)
_bridge = BridgeClient()


def _call(cmd: str, **args: Any) -> Any:
    try:
        return _bridge.call(cmd, **{k: v for k, v in args.items() if v is not None})
    except BridgeError as exc:
        return {"error": str(exc)}


@mcp.tool()
def bridge_status() -> Any:
    """Check that Rhino and the bridge are running; shows Rhino version and whether Grasshopper is open."""
    return _call("ping")


@mcp.tool()
def gh_create_script(
    code: str,
    language: Literal["python", "csharp", "ironpython"] = "python",
    inputs: list[str | dict] | None = None,
    outputs: list[str] | None = None,
    nickname: str | None = None,
    x: float = 100,
    y: float = 100,
) -> Any:
    """Create a script component on the Grasshopper canvas with the given code.

    inputs: names, or dicts {"name": "pts", "access": "item"|"list"|"tree", "optional": bool,
            "description": str}. Defaults keep the component's x/y inputs.
    outputs: output names (defaults keep "a").
    Returns the component (guid, params, data preview) plus `errors` from the first solve.
    """
    return _call("gh_create_script", code=code, language=language, inputs=inputs,
                 outputs=outputs, nickname=nickname, x=x, y=y)


@mcp.tool()
def gh_update_script(
    component: str,
    code: str | None = None,
    inputs: list[str | dict] | None = None,
    outputs: list[str] | None = None,
    nickname: str | None = None,
) -> Any:
    """Change an existing script component's code and/or parameters, then recompute it.

    Omit any argument to leave it unchanged. Returns new state and `errors`.
    """
    return _call("gh_update_script", component=component, code=code, inputs=inputs,
                 outputs=outputs, nickname=nickname)


@mcp.tool()
def gh_read_script(component: str) -> Any:
    """Read a script component's code, parameters, output data preview and runtime messages."""
    return _call("gh_read_script", component=component)


@mcp.tool()
def gh_list(filter: str | None = None, with_data: bool = False) -> Any:
    """List objects on the Grasshopper canvas (guid, nickname, params, wires, messages).

    filter: optional substring of name/nickname. with_data: include output data previews.
    """
    return _call("gh_list", filter=filter, with_data=with_data)


@mcp.tool()
def gh_add_component(name: str, x: float = 100, y: float = 100, nickname: str | None = None) -> Any:
    """Place any Grasshopper component by its name, e.g. "Number Slider", "Panel", "Loft",
    "Construct Point", "Divide Curve". Returns its guid and parameters."""
    return _call("gh_add_component", name=name, x=x, y=y, nickname=nickname)


@mcp.tool()
def gh_connect(
    source: str,
    target: str,
    source_output: str | int | None = None,
    target_input: str | int | None = None,
    keep_existing: bool = True,
) -> Any:
    """Wire source's output into target's input. Params by nickname, name or index
    (default: first). keep_existing=False replaces wires already on that input."""
    return _call("gh_connect", source=source, target=target, source_output=source_output,
                 target_input=target_input, keep_existing=keep_existing)


@mcp.tool()
def gh_disconnect(target: str, target_input: str | int | None = None) -> Any:
    """Remove all wires going into one input of a component."""
    return _call("gh_disconnect", target=target, target_input=target_input)


@mcp.tool()
def gh_delete(component: str) -> Any:
    """Delete a component from the canvas."""
    return _call("gh_delete", component=component)


@mcp.tool()
def gh_solve() -> Any:
    """Recompute the whole Grasshopper definition and list components with errors/warnings."""
    return _call("gh_solve")


@mcp.tool()
def rhino_run_macro(macro: str, wait: bool = False) -> Any:
    """Run a Rhino command macro, e.g. "_Box 0,0,0 10,10,0 5" or "_Zoom _All _Extents".

    wait=False types it into the command line (interactive commands keep prompting the user).
    wait=True runs it as a script and waits for it to finish.
    """
    return _call("run_command", macro=macro, mode="script" if wait else "keystrokes")


@mcp.tool()
def rhino_selection() -> Any:
    """What is selected in Rhino right now (ids, geometry types, layers)."""
    return _call("get_selection")


@mcp.tool()
def gh_add_slider(nickname: str, min: float, max: float, value: float, integer: bool = False,
                  x: float = 100, y: float = 100) -> Any:
    """Place a number slider with a range and start value."""
    return _call("gh_add_slider", nickname=nickname, min=min, max=max, value=value,
                 integer=integer, x=x, y=y)


@mcp.tool()
def gh_add_geometry_input(nickname: str, x: float = 100, y: float = 100) -> Any:
    """Place a Geometry parameter that references the objects currently selected in Rhino."""
    return _call("gh_add_geometry_input", nickname=nickname, x=x, y=y)


@mcp.tool()
def gh_recipes() -> Any:
    """Tested Grasshopper plans (title, inputs, outputs, code) to build or adapt."""
    return {name: factory("").to_dict() for name, (factory, _words) in RECIPES.items()}


@mcp.tool()
def gh_build(
    title: str,
    code: str,
    outputs: list[str],
    inputs: list[dict],
    summary: str = "",
    confirm: bool = False,
    recipe: str | None = None,
) -> Any:
    """Build a whole definition in one call: inputs -> one Python 3 script -> outputs.

    inputs: [{"name", "type": "geometry"|"number"|"integer"|"bool", "min", "max", "value",
              "source": "selection" (geometry from the current Rhino selection), "description"}].
    Geometry inputs arrive in the script as lists. Sliders/toggles are created and wired, all
    components are grouped, the definition is solved, and errors are returned so you can fix
    them with gh_update_script. recipe: build a tested recipe by name instead (ignores code).
    confirm=True shows the user a Yes/No dialog in Rhino first.
    """
    if recipe:
        if recipe not in RECIPES:
            return {"error": f"unknown recipe {recipe!r}; have {sorted(RECIPES)}"}
        plan = RECIPES[recipe][0](summary or title)
    else:
        plan = Plan(title=title, summary=summary, outputs=outputs, code=code,
                    inputs=[Input(**{k: v for k, v in i.items() if k in Input.__dataclass_fields__})
                            for i in inputs])
    try:
        return Builder(BridgeClient(timeout=900), None, confirm=confirm).build(plan).to_dict()
    except BridgeError as exc:
        return {"error": str(exc)}


_rules = RuleMapper()


@mcp.tool()
def voice_command(text: str, run: bool = False) -> Any:
    """How a spoken phrase maps to a Rhino command ("select previous" -> _SelPrev).

    run=True types it into Rhino's command line (the user confirms with Enter).
    """
    try:
        _rules.set_commands(_bridge.call("list_rhino_commands")["commands"])
    except BridgeError:
        pass
    match = _rules.map(text)
    if match is None:
        return {"text": text, "macro": None, "hint": "not a direct command; needs the model"}
    out = {"text": text, "macro": match.macro, "source": match.source}
    if run:
        out["sent"] = _call("run_command", macro=match.macro, enter=False)
    return out


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
