"""Put a Plan on the Grasshopper canvas through the bridge: confirm, build, wire, solve, repair."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..bridge_client import BridgeClient
from .recipes import Plan

log = logging.getLogger("rhino_voice")

ROW = 56          # vertical spacing between input components
SCRIPT_DX = 330   # horizontal distance from inputs to the script


@dataclass
class BuildResult:
    status: str                      # built | built_with_errors | cancelled | failed
    title: str
    script: str | None = None        # script component guid
    components: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    repairs: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def describe(plan: Plan, selection_count: int) -> str:
    lines = [plan.summary, ""]
    for inp in plan.inputs:
        if inp.type == "geometry":
            if selection_count:
                lines.append(f"• {inp.name}: the {selection_count} object(s) selected in Rhino")
            else:
                lines.append(f"• {inp.name}: NOTHING SELECTED. Select it in Rhino first, or set it later")
        elif inp.type == "bool":
            lines.append(f"• {inp.name}: toggle = {inp.value}")
        else:
            lines.append(f"• {inp.name}: slider {inp.min:g}–{inp.max:g}, start {inp.value:g}")
    lines += ["", "Outputs: " + ", ".join(plan.outputs), "", "Build it in Grasshopper?"]
    return "\n".join(lines)


def _messages(info: dict, level: str) -> list[str]:
    return [m["text"] for m in info.get("messages", []) if m["level"] == level]


class Builder:
    def __init__(self, bridge: BridgeClient, planner=None, confirm: bool = True, max_repairs: int = 2):
        self.bridge = bridge
        self.planner = planner
        self.confirm = confirm
        self.max_repairs = max_repairs

    def say(self, text: str) -> None:
        try:
            self.bridge.call("rhino_message", text=text)
        except Exception:  # noqa: BLE001  (feedback is best-effort)
            pass

    def build(self, plan: Plan) -> BuildResult:
        result = BuildResult("failed", plan.title, notes=list(plan.notes))
        selection = self.bridge.call("get_selection")
        sel_count = int(selection.get("count", 0))

        if self.confirm:
            answer = self.bridge.call("confirm", title=f"kazi: {plan.title}",
                                      message=describe(plan, sel_count))
            if not answer.get("ok"):
                result.status = "cancelled"
                self.say(f"cancelled '{plan.title}'")
                return result

        spot = self.bridge.call("gh_free_spot")
        x0, y0 = float(spot["x"]), float(spot["y"])
        ids: dict[str, str] = {}
        for i, inp in enumerate(plan.inputs):
            pos = {"x": x0, "y": y0 + i * ROW}
            if inp.type == "geometry":
                info = self.bridge.call("gh_add_geometry_input", nickname=inp.name,
                                        from_selection=inp.source == "selection", **pos)
                if not info.get("objects"):
                    result.warnings.append(f"'{inp.name}' is empty: select geometry in Rhino, then "
                                           f"right-click the '{inp.name}' parameter > Set Multiple Geometries")
            elif inp.type == "bool":
                info = self.bridge.call("gh_add_toggle", nickname=inp.name, value=bool(inp.value), **pos)
            else:
                info = self.bridge.call(
                    "gh_add_slider", nickname=inp.name, integer=inp.type == "integer",
                    min=inp.min if inp.min is not None else 0,
                    max=inp.max if inp.max is not None else 10,
                    value=inp.value if inp.value is not None else (inp.min or 0), **pos)
            ids[inp.name] = info["guid"]

        script_inputs = [{"name": inp.name, "access": "list" if inp.type == "geometry" else "item",
                          "description": inp.description} for inp in plan.inputs]
        script = self.bridge.call(
            "gh_create_script", code=plan.code, language=plan.language, inputs=script_inputs,
            outputs=plan.outputs, nickname=plan.title, x=x0 + SCRIPT_DX,
            y=y0 + max(0, len(plan.inputs) - 1) * ROW / 2, recompute=False)
        result.script = script["guid"]

        for inp in plan.inputs:
            self.bridge.call("gh_connect", source=ids[inp.name], target=result.script,
                             target_input=inp.name, keep_existing=False)

        result.components = [*ids.values(), result.script]
        group = self.bridge.call("gh_group", components=result.components, name=plan.title)
        sliders = {inp.name: ids[inp.name] for inp in plan.inputs if inp.type in ("number", "integer")}
        self.bridge.call("kazi_record_build", title=plan.title, group=group.get("group"),
                         script=result.script, components=result.components, sliders=sliders,
                         request=plan.summary, recipe=plan.recipe)

        info = self._solve(result.script)
        errors = _messages(info, "error")
        while errors and self.planner is not None and result.repairs < self.max_repairs:
            self.say(f"'{plan.title}' has errors, asking the model to fix them ({result.repairs + 1})")
            new_code = self.planner.repair(plan, errors)
            if not new_code:
                break
            plan.code = new_code
            result.repairs += 1
            self.bridge.call("gh_update_script", component=result.script, code=new_code, recompute=False)
            info = self._solve(result.script)
            errors = _messages(info, "error")

        result.errors = errors
        result.warnings += _messages(info, "warning")
        result.status = "built_with_errors" if errors else "built"
        self.say(f"built '{plan.title}'" + (f" with {len(errors)} error(s)" if errors else "")
                 + (f" ({result.repairs} fix(es))" if result.repairs else ""))
        return result

    def _solve(self, guid: str) -> dict:
        self.bridge.call("gh_solve")
        return self.bridge.call("gh_read_script", component=guid)
