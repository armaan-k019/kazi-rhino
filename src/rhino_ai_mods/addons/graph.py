"""A GraphPlan is a small Grasshopper definition made of real components (from any plug-in),
sliders, toggles, panels, script helpers and the wires between them. GraphBuilder puts one on
the canvas through the bridge: confirm, check everything is installed, place, wire, group,
solve. It is the plug-in counterpart of gh/builder.py, which builds one-script definitions.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field

from ..bridge_client import BridgeClient, BridgeError
from ..gh.builder import BuildResult
from .registry import ADDONS

log = logging.getLogger("rhino_voice")

COL_DX = 250      # horizontal distance between columns of components
ROW_DY = 80       # vertical distance between components in a column
INPUT_DY = 50     # ... between sliders / toggles / panels


@dataclass
class Node:
    id: str
    kind: str                       # geometry | slider | toggle | panel | component | script
    #                                 | build_sliders | build_output  (things kazi built before)
    label: str = ""                 # nickname on the canvas
    names: list[str] = field(default_factory=list)   # component: candidate names, best first
    addon: str | None = None        # component: which add-on it must come from (None = any)
    categories: list[str] = field(default_factory=list)  # component: tab names, when not an add-on
    optional: bool = False          # component: leave it out (with its wires) when not installed
    set: dict = field(default_factory=dict)          # component: {input name: typed-in value}
    min: float | None = None        # slider
    max: float | None = None
    value: float | bool | None = None                # slider / toggle
    integer: bool = False
    text: str = ""                  # panel
    code: str = ""                  # script
    inputs: list[dict] = field(default_factory=list)   # script: [{"name", "access"}]
    outputs: list[str] = field(default_factory=list)   # script
    source: str | None = None       # geometry: "selection"
    description: str = ""
    hops_path: str | None = None    # component: file or URL for a Hops component


@dataclass
class Wire:
    src: str
    dst: str
    out: list = field(default_factory=list)   # candidate output names / nicknames / index
    inp: list = field(default_factory=list)   # candidate input names / nicknames / index
    mapping: str | None = None                # flatten | graft


@dataclass
class GraphPlan:
    title: str
    summary: str
    nodes: list[Node] = field(default_factory=list)
    wires: list[Wire] = field(default_factory=list)
    main: str | None = None         # node whose outputs are "the result" (baked by KaziBake)
    recipe: str | None = None
    addons: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    kind: str = "graph"

    # -- building helpers (used by recipes) ---------------------------------- #
    def _add(self, node: Node) -> str:
        if any(n.id == node.id for n in self.nodes):
            raise ValueError(f"duplicate node id {node.id!r}")
        node.label = node.label or node.id
        self.nodes.append(node)
        return node.id

    def geometry(self, id: str, description: str = "", source: str | None = "selection") -> str:
        return self._add(Node(id, "geometry", source=source, description=description))

    def slider(self, id: str, value: float, lo: float, hi: float, integer: bool = False,
               description: str = "") -> str:
        lo, hi = min(lo, value), max(hi, value)
        return self._add(Node(id, "slider", value=value, min=lo, max=hi, integer=integer,
                              description=description))

    def toggle(self, id: str, value: bool = False, description: str = "") -> str:
        return self._add(Node(id, "toggle", value=bool(value), description=description))

    def panel(self, id: str, text: str, description: str = "") -> str:
        return self._add(Node(id, "panel", text=text, description=description))

    def component(self, id: str, names, addon: str | None = None, set: dict | None = None,
                  optional: bool = False, categories=(), label: str = "", **extra) -> str:
        names = [names] if isinstance(names, str) else list(names)
        if addon and addon not in self.addons:
            self.addons.append(addon)
        return self._add(Node(id, "component", names=names, addon=addon, set=dict(set or {}),
                              optional=optional, categories=list(categories),
                              label=label or id, **extra))

    def script(self, id: str, code: str, inputs: list, outputs: list[str]) -> str:
        ins = [{"name": i, "access": "item"} if isinstance(i, str) else dict(i) for i in inputs]
        return self._add(Node(id, "script", code=code, inputs=ins, outputs=list(outputs)))

    def previous(self, id: str, what: str) -> str:
        """what: 'sliders' or 'output' of the last thing kazi built on this canvas."""
        return self._add(Node(id, "build_" + what))

    def wire(self, src: str, dst: str, inp=None, out=None, mapping: str | None = None) -> None:
        def many(v):
            return [] if v is None else (list(v) if isinstance(v, (list, tuple)) else [v])
        self.wires.append(Wire(src, dst, many(out), many(inp), mapping))

    # -- reading ------------------------------------------------------------- #
    def node(self, id: str) -> Node:
        for n in self.nodes:
            if n.id == id:
                return n
        raise KeyError(id)

    def components(self) -> list[Node]:
        return [n for n in self.nodes if n.kind == "component"]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "GraphPlan":
        nodes = [Node(**{k: v for k, v in n.items() if k in Node.__dataclass_fields__})
                 for n in data.get("nodes", [])]
        wires = []
        for w in data.get("wires", []):
            w = {k: v for k, v in w.items() if k in Wire.__dataclass_fields__}
            for key in ("out", "inp"):
                v = w.get(key)
                w[key] = [] if v is None else (list(v) if isinstance(v, (list, tuple)) else [v])
            wires.append(Wire(**w))
        plan = cls(title=str(data.get("title") or "Add-on definition"),
                   summary=str(data.get("summary") or ""), nodes=nodes, wires=wires,
                   main=data.get("main"), recipe=data.get("recipe"),
                   addons=list(data.get("addons") or []), notes=list(data.get("notes") or []))
        for n in plan.nodes:
            n.label = n.label or n.id
            if n.addon and n.addon not in plan.addons:
                plan.addons.append(n.addon)
        return plan

    def validate(self) -> list[str]:
        """Problems that make the plan unbuildable (empty list = fine)."""
        problems = []
        ids = [n.id for n in self.nodes]
        if len(set(ids)) != len(ids):
            problems.append("node ids are not unique")
        kinds = {"geometry", "slider", "toggle", "panel", "component", "script",
                 "build_sliders", "build_output"}
        for n in self.nodes:
            if n.kind not in kinds:
                problems.append(f"node {n.id}: unknown kind {n.kind!r}")
            if n.kind == "component" and not n.names:
                problems.append(f"node {n.id}: a component needs a name")
            if n.kind == "component" and n.addon and n.addon not in ADDONS:
                problems.append(f"node {n.id}: unknown add-on {n.addon!r}")
            if n.kind == "script" and not n.code.strip():
                problems.append(f"node {n.id}: a script needs code")
        for w in self.wires:
            for end in (w.src, w.dst):
                if end not in ids:
                    problems.append(f"wire {w.src} -> {w.dst}: no node {end!r}")
            if w.mapping not in (None, "flatten", "graft"):
                problems.append(f"wire {w.src} -> {w.dst}: mapping must be flatten or graft")
        if self.main and self.main not in ids:
            problems.append(f"main node {self.main!r} does not exist")
        if not any(n.kind in ("component", "script") for n in self.nodes):
            problems.append("the plan places no components")
        return problems

    def columns(self) -> dict[str, int]:
        """Left-to-right column of every node: inputs first, each node right of what feeds it."""
        col = {n.id: 0 for n in self.nodes}
        for _ in range(len(self.nodes)):
            changed = False
            for w in self.wires:
                if w.src in col and w.dst in col and col[w.dst] < col[w.src] + 1:
                    col[w.dst] = col[w.src] + 1
                    changed = True
            if not changed:
                break
        return col


def describe(plan: GraphPlan, selection_count: int) -> str:
    """The text of the Yes/No dialog."""
    lines = [plan.summary, ""]
    comps = [n.names[0] for n in plan.components()]
    if plan.addons:
        lines.append("Uses: " + ", ".join(ADDONS[a].title for a in plan.addons if a in ADDONS))
    if comps:
        lines.append("Components: " + ", ".join(comps))
    for n in plan.nodes:
        if n.kind == "geometry":
            if selection_count:
                lines.append(f"• {n.label}: the {selection_count} object(s) selected in Rhino")
            else:
                lines.append(f"• {n.label}: NOTHING SELECTED. Select it in Rhino first, or set it later")
        elif n.kind == "slider":
            lines.append(f"• {n.label}: slider {n.min:g}–{n.max:g}, start {n.value:g}")
        elif n.kind == "toggle":
            lines.append(f"• {n.label}: toggle = {n.value}")
        elif n.kind == "panel":
            lines.append(f"• {n.label}: \"{n.text}\"")
    for note in plan.notes:
        lines.append("Note: " + note)
    lines += ["", "Build it in Grasshopper?"]
    return "\n".join(lines)


class GraphBuilder:
    def __init__(self, bridge: BridgeClient, confirm: bool = True):
        self.bridge = bridge
        self.confirm = confirm

    def say(self, text: str) -> None:
        try:
            self.bridge.call("rhino_message", text=text)
        except Exception:  # noqa: BLE001  (feedback is best-effort)
            pass

    # -- what is installed ---------------------------------------------------- #
    def _spec(self, node: Node) -> dict:
        spec: dict = {"names": node.names}
        if node.addon and node.addon in ADDONS:
            addon = ADDONS[node.addon]
            if addon.probe_scoped:
                spec.update(addon.scope())
        elif node.categories:
            spec["categories"] = node.categories
        return spec

    def check(self, plan: GraphPlan) -> tuple[list[Node], list[Node]]:
        """(missing required components, missing optional components). Places nothing."""
        comps = plan.components()
        if not comps:
            return [], []
        try:
            found = self.bridge.call("gh_resolve", components=[self._spec(n) for n in comps])
        except BridgeError as exc:
            if "Unknown cmd" in str(exc):
                raise BridgeError("The bridge running in Rhino is older than this feature. "
                                  "Run KaziStart in Rhino again to reload it.") from exc
            raise
        missing = [n for n, r in zip(comps, found["components"]) if not r.get("found")]
        return [n for n in missing if not n.optional], [n for n in missing if n.optional]

    # -- build ---------------------------------------------------------------- #
    def build(self, plan: GraphPlan) -> BuildResult:
        result = BuildResult("failed", plan.title, notes=list(plan.notes))
        problems = plan.validate()
        if problems:
            result.errors = problems
            return result

        required, optional = self.check(plan)
        if required:
            addons = [a for a in dict.fromkeys(n.addon for n in required) if a in ADDONS]
            result.status = "missing_addon"
            result.errors = [f"'{n.names[0]}' is not installed in Grasshopper"
                             + (f" ({ADDONS[n.addon].title})" if n.addon in ADDONS else "")
                             for n in required]
            result.notes += [ADDONS[a].install_hint() for a in addons]
            result.notes.append("Nothing was added to the canvas.")
            self.say(f"can't build '{plan.title}': " + "; ".join(result.errors)
                     + ". " + " ".join(ADDONS[a].install_hint() for a in addons))
            return result
        skipped = {n.id for n in optional}
        for n in optional:
            result.warnings.append(f"left out '{n.names[0]}' (not installed)")

        selection = self.bridge.call("get_selection")
        sel_count = int(selection.get("count", 0))
        if self.confirm:
            answer = self.bridge.call("confirm", title=f"kazi: {plan.title}",
                                      message=describe(plan, sel_count))
            if not answer.get("ok"):
                result.status = "cancelled"
                self.say(f"cancelled '{plan.title}'")
                return result

        previous = self._previous_build(plan, result)
        ids: dict[str, list[str]] = {}       # node id -> canvas guid(s)
        outs: dict[str, list] = {}           # node id -> output to use when a wire names none
        placed: list[str] = []
        sliders: dict[str, str] = {}
        try:
            self._place_all(plan, skipped, previous, ids, outs, placed, sliders, result)
        except BridgeError as exc:
            if placed:
                try:
                    self.bridge.call("gh_delete_many", components=placed)
                except BridgeError:
                    pass
            result.errors = [str(exc)]
            result.notes.append("Nothing was left on the canvas.")
            self.say(f"could not build '{plan.title}': {exc}")
            return result

        for w in plan.wires:
            if w.src in skipped or w.dst in skipped or not ids.get(w.src) or not ids.get(w.dst):
                continue
            for src in ids[w.src]:
                try:
                    self.bridge.call("gh_wire", source=src, target=ids[w.dst][0],
                                     source_output=w.out or outs.get(w.src) or None,
                                     target_input=w.inp or None, mapping=w.mapping,
                                     keep_existing=True)
                except BridgeError as exc:
                    result.errors.append(f"wire {w.src} → {w.dst}: {exc}")

        main = ids.get(plan.main or "", [None])[0] or next(
            (ids[n.id][0] for n in reversed(plan.nodes)
             if n.kind in ("component", "script") and ids.get(n.id)), None)
        result.script = main
        result.components = placed
        group = self.bridge.call("gh_group", components=placed, name=plan.title)
        self.bridge.call("kazi_record_build", title=plan.title, group=group.get("group"),
                         script=main, components=placed, sliders=sliders,
                         request=plan.summary, recipe=plan.recipe)

        solved = self.bridge.call("gh_solve")
        mine = set(placed)
        for problem in solved.get("problems", []):
            if problem.get("guid") not in mine:
                continue
            for m in problem.get("messages", []):
                text = f"{problem.get('nickname')}: {m['text']}"
                if m["level"] == "error":
                    result.errors.append(text)
                elif m["level"] == "warning":
                    result.warnings.append(text)
        result.status = "built_with_errors" if result.errors else "built"
        self.say(f"built '{plan.title}'" + (f" with {len(result.errors)} problem(s)" if result.errors else ""))
        return result

    def _previous_build(self, plan: GraphPlan, result: BuildResult) -> dict | None:
        if not any(n.kind.startswith("build_") for n in plan.nodes):
            return None
        builds = self.bridge.call("kazi_builds").get("builds") or []
        if not builds:
            result.warnings.append("Nothing built with kazi yet on this canvas, so the sliders and "
                                   "geometry to work on are not wired. Wire your own in.")
            return None
        return builds[-1]

    def _place_all(self, plan, skipped, previous, ids, outs, placed, sliders, result) -> None:
        spot = self.bridge.call("gh_free_spot")
        x0, y0 = float(spot["x"]), float(spot["y"])
        columns = plan.columns()
        next_y: dict[int, float] = {}
        for n in plan.nodes:
            if n.id in skipped:
                continue
            col = columns[n.id]
            pos = {"x": x0 + col * COL_DX, "y": next_y.get(col, y0)}
            step = ROW_DY if n.kind in ("component", "script") else INPUT_DY
            if n.kind == "component":
                step += 12 * max(0, len(n.set))

            if n.kind == "build_sliders":
                ids[n.id] = list((previous or {}).get("sliders", {}).values())
                continue
            if n.kind == "build_output":
                script = (previous or {}).get("script")
                if script:
                    info = self.bridge.call("gh_inspect", component=script)
                    names = [p["nickname"] for p in info.get("outputs", []) if p["nickname"] != "out"]
                    ids[n.id] = [script]
                    outs[n.id] = names[:1]
                continue

            if n.kind == "geometry":
                info = self.bridge.call("gh_add_geometry_input", nickname=n.label,
                                        from_selection=n.source == "selection", **pos)
                if not info.get("objects"):
                    result.warnings.append(
                        f"'{n.label}' is empty: select geometry in Rhino, then right-click the "
                        f"'{n.label}' parameter > Set Multiple Geometries")
            elif n.kind == "slider":
                info = self.bridge.call("gh_add_slider", nickname=n.label, integer=n.integer,
                                        min=n.min, max=n.max, value=n.value, **pos)
                sliders[n.label] = info["guid"]
            elif n.kind == "toggle":
                info = self.bridge.call("gh_add_toggle", nickname=n.label, value=bool(n.value), **pos)
            elif n.kind == "panel":
                info = self.bridge.call("gh_add_panel", nickname=n.label, text=n.text, **pos)
                step = ROW_DY
            elif n.kind == "script":
                info = self.bridge.call("gh_create_script", code=n.code, language="python",
                                        inputs=n.inputs, outputs=n.outputs, nickname=n.label,
                                        recompute=False, **pos)
                outs[n.id] = n.outputs[:1]
            else:
                info = self.bridge.call("gh_place", nickname=None, set=n.set or None,
                                        **self._spec(n), **pos)
                for problem in info.get("problems", []):
                    result.warnings.append(f"{n.names[0]}: {problem}")
            ids[n.id] = [info["guid"]]
            placed.append(info["guid"])
            if n.kind == "component" and n.hops_path:
                self.bridge.call("gh_hops_set_path", component=info["guid"], path=n.hops_path)
            next_y[col] = pos["y"] + step
