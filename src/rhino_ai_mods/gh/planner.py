"""Turn a spoken Grasshopper request into a Plan, with a model or a recipe."""

from __future__ import annotations

import json
import logging
import re

from .recipes import Plan, match_recipe, voronoi_facade

log = logging.getLogger("rhino_voice")

SYSTEM_PROMPT = """\
You are a computational designer writing Grasshopper definitions for Rhino 8 from an
architect's spoken request. You produce ONE Python 3 script component plus its inputs.

Reply with exactly two fenced blocks and nothing else:

```json
{"title": "...", "summary": "one sentence an architect understands",
 "inputs": [
   {"name": "facade", "type": "geometry", "source": "selection", "description": "..."},
   {"name": "count", "type": "integer", "min": 5, "max": 400, "value": 60, "description": "..."},
   {"name": "depth", "type": "number", "min": 0, "max": 2, "value": 0.3, "description": "..."},
   {"name": "flip", "type": "bool", "value": false, "description": "..."}
 ],
 "outputs": ["panels", "curves"]}
```
```python
<the script>
```

Inputs:
- type is "geometry" (comes from what the user has selected in Rhino; always arrives as a
  Python list), "number", "integer" (number sliders) or "bool" (toggle). Give every
  number a sensible min/max/value in metres. Use snake_case names. Expose the design
  parameters the request mentions ("that does xyz") as sliders.
- Use at most one geometry input unless the request clearly needs two.

Script rules (Rhino 8, CPython 3, inside a Grasshopper script component):
- Inputs are global variables with the input names. Assign every output name at the end.
- `import Rhino.Geometry as rg`. Only RhinoCommon, Grasshopper, System, math, random.
  `import ghpythonlib.components as ghcomp` is allowed for Grasshopper components in code.
- Geometry inputs may be None or empty and may be Brep, Extrusion, Surface, Curve or Mesh:
  convert (Extrusion.ToBrep(), Brep.Faces) and handle every case. If required input is
  missing, add a warning with ghenv.Component.AddRuntimeMessage(
  Grasshopper.Kernel.GH_RuntimeMessageLevel.Warning, "...") and output empty lists.
- Tolerance: Rhino.RhinoDoc.ActiveDoc.ModelAbsoluteTolerance.
- Outputs should be geometry (curves, breps, points) or lists of them. No printing.
- Keep it robust over clever: the script must run without errors on the first try.

Here is a tested example of the format, for the request "voronoi pattern on the facade":
"""

REPAIR_PROMPT = """\
The script you wrote ran in Grasshopper with these problems:

{errors}

Current script:
```python
{code}
```

Fix it. Reply with only one ```python block containing the full corrected script. Keep the same
input and output names: inputs {inputs}; outputs {outputs}."""


def _example() -> str:
    plan = voronoi_facade("")
    header = {k: v for k, v in plan.to_dict().items() if k in ("title", "summary", "inputs", "outputs")}
    return f"```json\n{json.dumps(header, indent=1)}\n```\n```python\n{plan.code}\n```"


def _blocks(text: str, lang: str) -> list[str]:
    return re.findall(rf"```{lang}\s*\n(.*?)```", text, re.S)


def parse_plan(text: str) -> Plan | None:
    js, py = _blocks(text, "json"), _blocks(text, "python")
    if not js or not py:
        return None
    try:
        data = json.loads(js[0])
    except json.JSONDecodeError:
        return None
    plan = Plan.from_dict(data, code=py[0])
    if not plan.code.strip() or not plan.outputs:
        return None
    return plan


class Planner:
    """backend: any object with complete(messages, max_tokens) -> str (see voice/llm.py)."""

    def __init__(self, backend=None):
        self.backend = backend

    def plan(self, request: str) -> Plan:
        recipe = match_recipe(request)
        if self.backend is None:
            if recipe is None:
                raise LookupError(
                    "No recipe matches that and no model is configured for Grasshopper. "
                    "Start rhino-voice with --gh-llm anthropic or --gh-llm hf-api.")
            return recipe
        user = f"Request: {request}"
        if recipe is not None:
            user += ("\n\nA tested recipe for this already exists (below). Start from it and only "
                     "change what the request asks for beyond it.\n\n```python\n" + recipe.code + "\n```")
        messages = [{"role": "system", "content": SYSTEM_PROMPT + "\n" + _example()},
                    {"role": "user", "content": user}]
        try:
            reply = self.backend.complete(messages, max_tokens=6000)
        except Exception as exc:  # noqa: BLE001  (network, quota, model errors)
            log.warning("Grasshopper model failed (%s)", exc)
            reply = ""
        plan = parse_plan(reply)
        if plan is None:
            if recipe is not None:
                log.warning("model reply unusable; using the %s recipe", recipe.recipe)
                recipe.notes.append("The model's answer was unusable, so the built-in recipe was used.")
                return recipe
            raise ValueError("The model didn't return a usable Grasshopper plan. Try rephrasing.")
        plan.recipe = recipe.recipe if recipe else None
        return plan

    def repair(self, plan: Plan, errors: list[str]) -> str | None:
        if self.backend is None:
            return None
        prompt = REPAIR_PROMPT.format(errors="\n".join(errors), code=plan.code,
                                      inputs=", ".join(i.name for i in plan.inputs),
                                      outputs=", ".join(plan.outputs))
        messages = [{"role": "system", "content": SYSTEM_PROMPT + "\n" + _example()},
                    {"role": "user", "content": prompt}]
        try:
            blocks = _blocks(self.backend.complete(messages, max_tokens=6000), "python")
        except Exception as exc:  # noqa: BLE001
            log.warning("repair failed (%s)", exc)
            return None
        return blocks[0] if blocks else None
