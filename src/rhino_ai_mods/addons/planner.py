"""Plug the add-ons into the voice / text pipeline without changing how it works.

AddonPlanner wraps the normal Planner: a request that names an add-on ("panelize this facade
with LunchBox") or is about something only an add-on does ("sun path") becomes a GraphPlan of
that add-on's components; everything else goes to the wrapped planner untouched.
AddonBuilder wraps the normal Builder the same way.
"""

from __future__ import annotations

import json
import logging
import re

from ..gh.recipes import match_recipe
from . import catalog
from .graph import GraphBuilder, GraphPlan
from .recipes import ADDON_RECIPES, _clean
from .registry import ADDONS, mentioned

log = logging.getLogger("rhino_voice")

GRAPH_PROMPT = """\
You wire up Grasshopper definitions for an architect from a spoken request, using components
of the add-on "{title}" ({what_for}). Reply with ONE fenced json block and nothing else:

```json
{{"title": "...", "summary": "one sentence an architect understands",
 "nodes": [
  {{"id": "facade", "kind": "geometry"}},
  {{"id": "u", "kind": "slider", "value": 10, "min": 1, "max": 60, "integer": true}},
  {{"id": "run", "kind": "toggle", "value": false}},
  {{"id": "layer", "kind": "panel", "text": "facade::panels"}},
  {{"id": "panels", "kind": "component", "names": ["Quad Panels"], "addon": "{addon}"}}
 ],
 "wires": [
  {{"src": "facade", "dst": "panels", "inp": ["Surface"]}},
  {{"src": "u", "dst": "panels", "inp": ["U Divisions"]}}
 ],
 "main": "panels"}}
```

Rules:
- kind is geometry (what the user has selected in Rhino), slider, toggle, panel or component.
- A component's "names" must be copied exactly from the list below, with "addon": "{addon}".
  For a standard Grasshopper component use "addon": null and its exact name.
- A wire goes from src's output "out" to dst's input "inp"; both are lists of exact parameter
  names from the list below (omit "out" to use the first output).
- Expose every number the request mentions as a slider with a sensible range.
- "main" is the component whose output is the result.

{title} components, as  Name (inputs) -> outputs :
{components}
"""


def named_component(request: str, addon: str) -> catalog.Component | None:
    """A component of this add-on that the request names word for word (longest wins)."""
    text = " " + re.sub(r"[^a-z0-9]+", " ", _clean(request)) + " "
    best = None
    for comp in catalog.load().of(addon):
        name = re.sub(r"^(?:lb|hb|df) ", "", re.sub(r"[^a-z0-9]+", " ", comp.name.lower()).strip())
        if len(name) < 7 or name == ADDONS[addon].title.lower():
            continue
        if f" {name} " in text and (best is None or len(name) > best[0]):
            best = (len(name), comp)
    return best[1] if best else None


def single_component(comp: catalog.Component) -> GraphPlan:
    """A plan that just places one component, ready to be wired by hand or by Claude."""
    title = ADDONS[comp.addon].title
    plan = GraphPlan(f"{title} {comp.name}", f"Place the {title} component \"{comp.name}\"."
                     + (f" {comp.description}" if comp.description else ""),
                     recipe=f"{comp.addon}_component")
    plan.component("component", [comp.name], comp.addon, label=comp.name)
    plan.main = "component"
    if comp.inputs:
        plan.notes.append("Inputs to wire: " + ", ".join(n for n, _k, _t in comp.inputs))
    return plan


def parse_graph(reply: str, addon: str) -> GraphPlan | None:
    """A model's reply -> GraphPlan, or None if it is not usable. Component names that are
    not in the add-on's catalogue make the whole plan unusable (models invent components)."""
    blocks = re.findall(r"```json\s*\n(.*?)```", reply or "", re.S)
    if not blocks:
        return None
    try:
        plan = GraphPlan.from_dict(json.loads(blocks[0]))
    except (ValueError, TypeError, AttributeError):
        return None
    if plan.validate():
        return None
    cat = catalog.load()
    for node in plan.nodes:
        if node.kind in ("script", "build_sliders", "build_output") or node.hops_path:
            return None            # the model may only place and wire components
        if node.kind == "component" and node.addon:
            if node.addon != addon or not any(cat.find(n, addon) for n in node.names):
                return None
    if not any(n.kind == "component" and n.addon == addon for n in plan.nodes):
        return None
    return plan


class AddonPlanner:
    def __init__(self, inner=None, backend=None):
        self.inner = inner
        self.backend = backend if backend is not None else getattr(inner, "backend", None)

    def addon_plan(self, request: str) -> GraphPlan | None:
        named = mentioned(_clean(request), strict=True)
        if not named:
            if match_recipe(request) is not None:
                return None                       # one of the built-in script recipes
            named = mentioned(_clean(request))
        for addon in named:
            if addon not in ADDON_RECIPES:
                continue
            recipe = ADDON_RECIPES[addon](request)
            comp = named_component(request, addon)
            if comp is None or any(catalog.norm(comp.name) == catalog.norm(n)
                                   for node in recipe.components() for n in node.names):
                return recipe
            # The request names a component the ready-made definition doesn't use.
            return self.model_plan(request, addon) or single_component(comp)
        return None

    def model_plan(self, request: str, addon: str) -> GraphPlan | None:
        if self.backend is None:
            return None
        a = ADDONS[addon]
        comps = catalog.load().of(addon)
        known = [c for c in comps if c.inputs is not None]
        lines = [c.line() for c in (known if len(known) >= 8 else comps)][:150]
        prompt = GRAPH_PROMPT.format(title=a.title, what_for=a.what_for, addon=addon,
                                     components="\n".join(lines))
        try:
            reply = self.backend.complete([{"role": "system", "content": prompt},
                                           {"role": "user", "content": f"Request: {request}"}],
                                          max_tokens=3000)
        except Exception as exc:  # noqa: BLE001  (network, quota, model errors)
            log.warning("add-on model failed (%s)", exc)
            return None
        plan = parse_graph(reply, addon)
        if plan is None:
            log.warning("add-on model reply unusable")
            return None
        plan.recipe = plan.recipe or f"{addon}_model"
        return plan

    def plan(self, request: str):
        plan = self.addon_plan(request)
        if plan is not None:
            return plan
        if self.inner is None:
            raise LookupError("That doesn't match an add-on recipe.")
        return self.inner.plan(request)

    def repair(self, plan, errors):
        return self.inner.repair(plan, errors) if self.inner is not None else None

    def __getattr__(self, name):          # anything else the wrapped planner offers
        if name == "inner" or self.inner is None:
            raise AttributeError(name)
        return getattr(self.inner, name)


class AddonBuilder:
    def __init__(self, inner, bridge=None, confirm: bool | None = None):
        self.inner = inner
        self.bridge = bridge if bridge is not None else inner.bridge
        self.confirm = inner.confirm if confirm is None else confirm

    def build(self, plan):
        if isinstance(plan, GraphPlan):
            return GraphBuilder(self.bridge, confirm=self.confirm).build(plan)
        return self.inner.build(plan)

    def __getattr__(self, name):          # say(), planner, ... of the wrapped builder
        return getattr(self.inner, name)
