"""kazi-addons: check, list and build Grasshopper add-on definitions from the terminal.

    kazi-addons check            which add-ons are installed + test every ready-made recipe
    kazi-addons list             what you can ask for
    kazi-addons find tween       search component names (add --offline to search without Rhino)
    kazi-addons build "panelize this facade with lunchbox 10 by 20"
    kazi-addons learn            save a list of every installed component
"""

from __future__ import annotations

import argparse
import json
import sys

from ..bridge_client import BridgeClient, BridgeError
from . import audit, catalog
from .graph import GraphBuilder
from .planner import AddonPlanner
from .recipes import recipe_list
from .registry import ADDONS


def _check(bridge) -> int:
    report = audit.audit(bridge)
    print("Add-ons")
    for aid, info in report["addons"].items():
        mark = "installed" if info["installed"] else "MISSING  "
        extra = f"  v{info['version']}" if info.get("version") else ""
        print(f"  {mark}  {info['title']}{extra}")
        if not info["installed"]:
            print(f"             {info['install']}")
    print("\nReady-made definitions")
    for recipe, r in report["recipes"].items():
        if r["ok"] is None:
            print(f"  skipped  {recipe}  (add-on not installed)")
            continue
        print(f"  {'ok     ' if r['ok'] else 'PROBLEM'}  {recipe}   say: \"{r['say']}\"")
        for line in r.get("problems", []):
            print(f"             {line}")
    for aid, c in report["catalog"].items():
        if c["listed_but_not_installed"]:
            print(f"\n{ADDONS[aid].title}: {len(c['listed_but_not_installed'])} listed component(s) "
                  f"not found in your version, e.g. {', '.join(c['listed_but_not_installed'][:5])}")
    if report.get("saved_to"):
        print(f"\nFull report: {report['saved_to']}")
    return 0 if report["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kazi-addons", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="which add-ons are installed, and do the recipes fit them")
    sub.add_parser("list", help="what you can ask for")
    sub.add_parser("learn", help="save a list of every installed component")
    find = sub.add_parser("find", help="search components")
    find.add_argument("query", nargs="+")
    find.add_argument("--addon", choices=sorted(ADDONS))
    find.add_argument("--offline", action="store_true", help="search the reference lists, not Rhino")
    build = sub.add_parser("build", help="build a definition from a sentence")
    build.add_argument("text", nargs="+")
    build.add_argument("--dry-run", action="store_true")
    build.add_argument("--yes", action="store_true", help="skip the Yes/No dialog in Rhino")
    args = parser.parse_args(argv)

    if args.cmd == "list":
        for item in recipe_list():
            print(f"{item['title']}  ({ADDONS[item['addon']].what_for})")
            for phrase in item["say"]:
                print(f"    \"{phrase}\"")
        return 0
    try:
        if args.cmd == "find" and args.offline:
            for c in catalog.load().search(" ".join(args.query), args.addon):
                print(f"[{ADDONS[c.addon].title}] {c.line()}")
            return 0
        if args.cmd == "build":
            plan = AddonPlanner().addon_plan(" ".join(args.text))
            if plan is None:
                print("No add-on recipe matches that. Try: kazi-addons list")
                return 2
            if args.dry_run:
                print(json.dumps(plan.to_dict(), indent=1))
                return 0
            result = GraphBuilder(BridgeClient(timeout=900), confirm=not args.yes).build(plan)
            print(json.dumps(result.to_dict(), indent=1))
            return 0 if result.status == "built" else 1
        bridge = BridgeClient(timeout=900)
        if args.cmd == "check":
            return _check(bridge)
        if args.cmd == "learn":
            print(json.dumps(audit.learn(bridge), indent=1))
            return 0
        scope = ADDONS[args.addon].scope() if args.addon and ADDONS[args.addon].probe_scoped else {}
        r = bridge.call("gh_search_components", query=" ".join(args.query), with_params=True, **scope)
        for c in r["components"]:
            ins = ", ".join(p["name"] for p in c.get("inputs", []))
            outs = ", ".join(p["name"] for p in c.get("outputs", []))
            print(f"[{c['category']}] {c['name']} ({ins}) -> {outs}")
        return 0
    except BridgeError as exc:
        print(f"Rhino bridge: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
