"""MCP tools for Grasshopper add-ons. register(mcp, call) adds them to the rhino-ai-mods server."""

from __future__ import annotations

from typing import Any, Callable

from ..bridge_client import BridgeClient, BridgeError
from . import audit, catalog
from .graph import GraphBuilder, GraphPlan
from .planner import AddonPlanner
from .recipes import EXAMPLES, recipe_list
from .registry import ADDONS

INSTRUCTIONS = """
Grasshopper add-ons (LunchBox, Ladybug Tools, Kangaroo 2, Weaverbird, Pufferfish, Elefront,
Human, Wallacei, Hops, Speckle, and anything else installed):
- gh_addons shows which are installed and how to install the rest.
- gh_addon_build builds a ready-made definition from a sentence ("panelize this facade with
  lunchbox 10 by 20", "ladybug sun hours study", "relax this mesh with kangaroo").
- For anything else: gh_find_component (exact names, inputs, outputs) -> gh_place_component ->
  gh_wire / gh_set_input, or all at once with gh_build_graph. Never guess a component or
  parameter name: look it up first. gh_inspect shows a component's data and messages.
"""


def register(mcp, call: Callable[..., Any], bridge_factory=lambda: BridgeClient(timeout=900)) -> None:
    def guarded(fn):
        try:
            return fn()
        except BridgeError as exc:
            return {"error": str(exc)}

    @mcp.tool()
    def gh_addons(check_recipes: bool = False) -> Any:
        """Which free Grasshopper add-ons are installed in this Rhino, what each is for, how to
        install the missing ones, and what can be asked of each.

        check_recipes=True also tests every ready-made definition against the installed
        components (no canvas changes) and saves the report to ~/.kazi-rhino/addons_audit.json.
        """
        def run():
            out = audit.audit(bridge_factory()) if check_recipes else audit.status(bridge_factory())
            out["ask_for"] = recipe_list()
            return out
        return guarded(run)

    @mcp.tool()
    def gh_find_component(query: str, addon: str | None = None, installed: bool = True,
                          with_params: bool = True, limit: int = 12) -> Any:
        """Find Grasshopper components by words in their name or description, with their exact
        inputs and outputs. addon: lunchbox | ladybug | kangaroo2 | weaverbird | pufferfish |
        elefront | human | wallacei | hops | speckle (omit to search every installed plug-in).

        installed=True asks the running Grasshopper (the truth for this machine).
        installed=False searches the built-in reference lists instead; works without Rhino.
        """
        if addon and addon not in ADDONS:
            return {"error": f"unknown add-on {addon!r}; have {sorted(ADDONS)}"}
        if not installed:
            hits = catalog.load().search(query, addon, limit)
            return {"source": "reference list", "count": len(hits),
                    "components": [c.to_dict() for c in hits]}
        scope = ADDONS[addon].scope() if addon and ADDONS[addon].probe_scoped else {}
        return call("gh_search_components", query=query, with_params=with_params, limit=limit,
                    **scope)

    @mcp.tool()
    def gh_place_component(name: str, addon: str | None = None, x: float | None = None,
                           y: float | None = None, set: dict | None = None,
                           guid: str | None = None) -> Any:
        """Place a component from any plug-in on the canvas. addon makes sure the right one is
        picked when several plug-ins use the same name ("Solver", "Offset Surface").
        set: values typed straight into inputs, e.g. {"U Divisions": 12, "Create Solid": true}.
        Omit x / y to put it below everything else. Returns guid, real inputs and outputs."""
        if addon and addon not in ADDONS:
            return {"error": f"unknown add-on {addon!r}; have {sorted(ADDONS)}"}

        def run():
            bridge = bridge_factory()
            pos = {"x": x, "y": y}
            if x is None or y is None:
                pos = bridge.call("gh_free_spot")
            scope = ADDONS[addon].scope() if addon and ADDONS[addon].probe_scoped else {}
            args = {"names": [name], "set": set, "guid": guid, **scope, **pos}
            return bridge.call("gh_place", **{k: v for k, v in args.items() if v is not None})
        return guarded(run)

    @mcp.tool()
    def gh_wire(source: str, target: str, source_output: str | int | list | None = None,
                target_input: str | int | list | None = None, flatten: bool = False,
                graft: bool = False, keep_existing: bool = True) -> Any:
        """Wire source's output into target's input. Like gh_connect, but parameter names are
        matched loosely ("goal objects" finds GoalObjects), a list of possible names may be
        given, and the input can be flattened or grafted."""
        return call("gh_wire", source=source, target=target, source_output=source_output,
                    target_input=target_input, keep_existing=keep_existing,
                    mapping="flatten" if flatten else ("graft" if graft else None))

    @mcp.tool()
    def gh_set_input(component: str, input: str | int, value: Any) -> Any:
        """Type a value into a component input (number, true / false, text, or a list of them),
        replacing any wires into it. Script-based components (Ladybug) can't hold values: wire
        a slider, toggle or panel instead."""
        return call("gh_set_input", component=component, input=input, value=value)

    @mcp.tool()
    def gh_add_panel(text: str, nickname: str = "note", x: float = 100, y: float = 100) -> Any:
        """Place a text panel (layer names, file paths, web addresses, notes)."""
        return call("gh_add_panel", text=text, nickname=nickname, x=x, y=y)

    @mcp.tool()
    def gh_add_toggle(nickname: str, value: bool = False, x: float = 100, y: float = 100) -> Any:
        """Place a True / False toggle (for 'run', 'bake' and similar inputs)."""
        return call("gh_add_toggle", nickname=nickname, value=value, x=x, y=y)

    @mcp.tool()
    def gh_inspect(component: str) -> Any:
        """One component in full: inputs, outputs, what is wired to what, a preview of the data
        in every parameter, and its errors and warnings."""
        return call("gh_inspect", component=component)

    @mcp.tool()
    def gh_hops_set_path(component: str, path: str) -> Any:
        """Point a Hops component at a .gh file or a web address (for example a Python
        ghhops-server endpoint). Its inputs and outputs appear once the path is set."""
        return call("gh_hops_set_path", component=component, path=path)

    @mcp.tool()
    def gh_addon_build(request: str, confirm: bool = False, dry_run: bool = False) -> Any:
        """Build a ready-made add-on definition from a sentence, exactly as the voice command
        does. Examples: "panelize this facade with lunchbox 10 by 20", "lunchbox diagrid",
        "weaverbird picture frame and thicken", "hanging shell with kangaroo", "tween these
        curves with pufferfish", "bake to layer facade with elefront", "ladybug radiation
        study", "optimize this with wallacei", "publish this to speckle".
        Geometry inputs take what is selected in Rhino. dry_run=True returns the plan only.
        confirm=True shows the user a Yes / No dialog in Rhino first."""
        plan = AddonPlanner().addon_plan(request)
        if plan is None:
            return {"error": "No add-on recipe matches that. Name the add-on, or use "
                             "gh_find_component + gh_build_graph.",
                    "examples": [p for p, _ in EXAMPLES]}
        if dry_run:
            return plan.to_dict()
        return guarded(lambda: GraphBuilder(bridge_factory(), confirm=confirm).build(plan).to_dict())

    @mcp.tool()
    def gh_build_graph(title: str, nodes: list[dict], wires: list[dict], summary: str = "",
                       main: str | None = None, confirm: bool = False,
                       check_only: bool = False) -> Any:
        """Build a whole definition of real components in one call: placed in tidy columns,
        wired, grouped, recorded (so KaziUndoBuild / KaziBake work) and solved.

        nodes: [{"id": "facade", "kind": "geometry"}                      (the Rhino selection)
                {"id": "u", "kind": "slider", "value": 10, "min": 1, "max": 60, "integer": true}
                {"id": "run", "kind": "toggle", "value": false}
                {"id": "layer", "kind": "panel", "text": "facade::glass"}
                {"id": "panels", "kind": "component", "names": ["Quad Panels"],
                 "addon": "lunchbox", "set": {"V Divisions": 6}}
                {"id": "calc", "kind": "script", "code": "...", "inputs": ["x"], "outputs": ["a"]}]
        wires: [{"src": "u", "dst": "panels", "inp": ["U Divisions", "U"], "out": [...],
                 "mapping": "flatten"|"graft"}]   inp / out: candidate names, or an index.
        main: id of the node whose outputs are the result.
        Nothing is placed if a component is not installed. check_only=True only reports
        whether every component and parameter name exists (use it before building).
        Returns status, guids, and errors such as a wire whose parameter was not found."""
        try:
            plan = GraphPlan.from_dict({"title": title, "summary": summary, "nodes": nodes,
                                        "wires": wires, "main": main})
        except TypeError as exc:
            return {"error": f"bad plan: {exc}"}
        problems = plan.validate()
        if problems:
            return {"error": "bad plan: " + "; ".join(problems)}
        if check_only:
            return guarded(lambda: audit.preflight(bridge_factory(), plan))
        return guarded(lambda: GraphBuilder(bridge_factory(), confirm=confirm).build(plan).to_dict())

    @mcp.tool()
    def gh_learn_components() -> Any:
        """Save a list of every component installed in this Grasshopper (all plug-ins, with
        inputs and outputs) to ~/.kazi-rhino/components.json. Takes up to a minute."""
        return guarded(lambda: audit.learn(bridge_factory()))
