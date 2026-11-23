"""Check the add-ons against the Grasshopper that is really running.

status()     which of the ten add-ons are installed, with install instructions for the rest
preflight()  would this plan build? (every component found, every wire finds its parameter)
audit()      status + every ready-made recipe preflighted + catalogue vs installed components
learn()      save a snapshot of every installed component (with inputs and outputs) to
             ~/.kazi-rhino/components.json, for Claude to search without Rhino running
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from ..bridge_client import BridgeClient
from . import catalog
from .graph import GraphBuilder, GraphPlan
from .recipes import EXAMPLES, match_addon_recipe
from .registry import ADDONS

AUDIT_PATH = catalog.LEARNED_PATH.with_name("addons_audit.json")


def _probe(addon) -> dict:
    spec: dict = {"names": list(addon.probe)}
    if addon.probe_scoped:
        spec.update(addon.scope())
    return spec


def status(bridge: BridgeClient) -> dict:
    addons = list(ADDONS.values())
    found = bridge.call("gh_resolve", components=[_probe(a) for a in addons])["components"]
    plugins = bridge.call("gh_plugins")
    libs = {lib["name"].lower(): lib for lib in plugins.get("libraries", [])}
    out = {}
    for addon, hit in zip(addons, found):
        info = {"title": addon.title, "installed": bool(hit.get("found")), "for": addon.what_for}
        if info["installed"]:
            lib = next((v for k, v in libs.items()
                        if any(name.lower() in k for name in addon.libraries)), None)
            if lib and lib.get("version"):
                info["version"] = lib["version"]
            info["components"] = sum(n for cat, n in plugins.get("categories", {}).items()
                                     if cat in addon.categories) if addon.probe_scoped else None
        else:
            info["install"] = addon.install_hint()
        if addon.notes:
            info["notes"] = list(addon.notes)
        out[addon.id] = info
    return {"addons": out, "installed": [a for a, i in out.items() if i["installed"]],
            "missing": [a for a, i in out.items() if not i["installed"]]}


def _match(params: list[dict], refs: list) -> dict | None:
    """Same rules as the bridge's gh_wire: exact name / nickname, then loose, then index."""
    if not refs:
        return params[0] if params else None
    for ref in refs:
        if isinstance(ref, int):
            if 0 <= ref < len(params):
                return params[ref]
            continue
        low = str(ref).lower()
        for p in params:
            if p["nickname"].lower() == low or p["name"].lower() == low:
                return p
    for ref in refs:
        if not isinstance(ref, int):
            n = catalog.norm(ref)
            for p in params:
                if n and n in (catalog.norm(p["nickname"]), catalog.norm(p["name"])):
                    return p
    return None


def preflight(bridge: BridgeClient, plan: GraphPlan) -> dict:
    """Check a plan against the installed components without placing anything."""
    builder = GraphBuilder(bridge, confirm=False)
    comps = plan.components()
    found = bridge.call("gh_resolve", components=[builder._spec(n) for n in comps],
                        with_params=True)["components"] if comps else []
    real = {n.id: r for n, r in zip(comps, found)}
    problems, loose = [], []
    for n in comps:
        if not real[n.id].get("found") and not n.optional:
            problems.append(f"'{n.names[0]}' is not installed")
    for w in plan.wires:
        for end, side, refs in ((w.dst, "inputs", w.inp), (w.src, "outputs", w.out)):
            info = real.get(end)
            if not info or not info.get("found") or side not in info:
                continue
            names = [r for r in refs if not isinstance(r, int)]
            hit = _match(info[side], refs)
            if hit is None:
                problems.append(f"{info['name']}: no {side[:-1]} named {names or refs} "
                                f"(it has {[p['name'] for p in info[side]]})")
            elif names and _match(info[side], names) is None:
                loose.append(f"{info['name']}: {side[:-1]} {names} matched by position "
                             f"to '{hit['name']}'")
    return {"ok": not problems, "problems": problems, "by_position": loose,
            "components": [{"wanted": n.names[0], "found": real[n.id].get("name"),
                            "tab": real[n.id].get("category")} for n in comps]}


def learn(bridge: BridgeClient, path: Path | None = None, with_params: bool = True,
          page: int = 150) -> dict:
    """Snapshot every installed component. Reading inputs and outputs creates each component
    once off-canvas, so the first run can take a minute."""
    path = Path(path or catalog.LEARNED_PATH)
    comps, offset, total = [], 0, None
    while total is None or offset < total:
        r = bridge.call("gh_component_dump", offset=offset, limit=page, with_params=with_params)
        total = int(r["total"])
        comps += r["components"]
        offset += page
        if not r["components"]:
            break
    data = {"saved": time.strftime("%Y-%m-%d %H:%M"), "count": len(comps), "components": comps}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    tabs: dict[str, int] = {}
    for c in comps:
        tabs[c["category"]] = tabs.get(c["category"], 0) + 1
    return {"saved_to": str(path), "components": len(comps), "tabs": dict(sorted(tabs.items()))}


def audit(bridge: BridgeClient, path: Path | None = None) -> dict:
    """The first-run self-test: what is installed, and does every ready-made recipe fit it?"""
    st = status(bridge)
    cat = catalog.load()
    report = {"checked": time.strftime("%Y-%m-%d %H:%M"), **st, "recipes": {}, "catalog": {}}
    for phrase, recipe in EXAMPLES:
        plan = match_addon_recipe(phrase)
        if not set(plan.addons) <= set(st["installed"]):
            report["recipes"][recipe] = {"ok": None, "skipped": "add-on not installed"}
            continue
        pf = preflight(bridge, plan)
        entry = {"ok": pf["ok"], "say": phrase}
        if pf["problems"]:
            entry["problems"] = pf["problems"]
        if pf["by_position"]:
            entry["by_position"] = pf["by_position"]
        report["recipes"][recipe] = entry
    for aid in st["installed"]:
        addon = ADDONS[aid]
        if not addon.probe_scoped:
            continue
        installed, offset = [], 0
        while True:
            r = bridge.call("gh_component_dump", offset=offset, limit=300, **addon.scope())
            installed += r["components"]
            offset += 300
            if offset >= int(r["total"]) or not r["components"]:
                break
        have = {catalog.norm(c["name"]) for c in installed} | {catalog.norm(c["nickname"]) for c in installed}
        listed = cat.of(aid)
        known = {catalog.norm(c.name) for c in listed}
        report["catalog"][aid] = {
            "installed": len(installed), "listed": len(listed),
            "listed_but_not_installed": sorted(c.name for c in listed if catalog.norm(c.name) not in have)[:40],
            "installed_but_not_listed": sorted(c["name"] for c in installed
                                               if catalog.norm(c["name"]) not in known)[:40]}
    report["ok"] = all(r["ok"] is not False for r in report["recipes"].values())
    path = Path(path or AUDIT_PATH)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=1), encoding="utf-8")
        report["saved_to"] = str(path)
    except OSError:
        pass
    return report
