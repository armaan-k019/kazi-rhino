"""The Plan data model shared by recipes, the planner and the builder."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field


@dataclass
class Input:
    name: str
    type: str = "number"          # number | integer | bool | geometry
    description: str = ""
    min: float | None = None
    max: float | None = None
    value: float | bool | None = None
    source: str | None = None     # "selection" for geometry taken from the Rhino selection


@dataclass
class Plan:
    title: str
    summary: str
    inputs: list[Input]
    outputs: list[str]
    code: str
    language: str = "python"
    recipe: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict, code: str | None = None) -> "Plan":
        inputs = []
        for raw in data.get("inputs", []):
            if isinstance(raw, str):
                raw = {"name": raw}
            known = {k: raw[k] for k in Input.__dataclass_fields__ if k in raw}
            inputs.append(Input(**known))
        return cls(
            title=str(data.get("title") or "Voice script"),
            summary=str(data.get("summary") or ""),
            inputs=inputs,
            outputs=[str(o) for o in data.get("outputs", ["result"])],
            code=code if code is not None else str(data.get("code") or ""),
            language=str(data.get("language") or "python"),
            recipe=data.get("recipe"),
        )


_HELPERS = r'''
import Rhino
import Rhino.Geometry as rg
import Grasshopper

TOL = Rhino.RhinoDoc.ActiveDoc.ModelAbsoluteTolerance if Rhino.RhinoDoc.ActiveDoc else 0.01


def warn(msg):
    ghenv.Component.AddRuntimeMessage(Grasshopper.Kernel.GH_RuntimeMessageLevel.Warning, msg)


def as_list(x):
    if x is None:
        return []
    return list(x) if isinstance(x, (list, tuple)) else [x]
'''


def _number(text: str, pattern: str, default: float) -> float:
    m = re.search(pattern, text.lower())
    if not m:
        return default
    try:
        return float(next(g for g in m.groups() if g))
    except (StopIteration, ValueError):
        return default
