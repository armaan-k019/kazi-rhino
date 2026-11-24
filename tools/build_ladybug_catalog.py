"""Rebuild the Ladybug Tools catalog from the official component sources on PyPI.

    pip download --no-deps ladybug-grasshopper honeybee-grasshopper-core \
        honeybee-grasshopper-radiance honeybee-grasshopper-energy dragonfly-grasshopper -d wheels
    (unzip each wheel into its own folder)
    python tools/build_ladybug_catalog.py <folder with the unzipped wheels> src/rhino_ai_mods/addons/data

Each component's source file states its Name, NickName, Category, SubCategory and documents
its inputs (Args) and outputs (Returns), so the catalog is exact for the version downloaded.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ATTR = re.compile(r"ghenv\.Component\.(\w+)\s*=\s*(['\"])(.*?)\2")
ITEM = re.compile(r"^ {4,8}([A-Za-z_][\w]*):\s*(.*)$")


def section(doc: str, head: str) -> list[tuple[str, str]]:
    m = re.search(rf"^\s*{head}:\s*$", doc, re.M)
    if not m:
        return []
    rest = doc[m.end():]
    stop = re.search(r"^\s*(Args|Returns):\s*$", rest, re.M)
    if stop:
        rest = rest[:stop.start()]
    items: list[list[str]] = []
    indent = None
    for line in rest.splitlines():
        if not line.strip():
            continue
        lead = len(line) - len(line.lstrip())
        m2 = ITEM.match(line)
        if m2 and (indent is None or lead == indent):
            indent = lead
            items.append([m2.group(1), m2.group(2).strip()])
        elif items:
            if len(items[-1][1]) < 160:
                items[-1][1] = (items[-1][1] + " " + line.strip()).strip()
    return [(n, d) for n, d in items]


def parse(path: Path) -> dict | None:
    text = path.read_text(encoding="utf-8", errors="replace")
    attrs = {k: v for k, _, v in ATTR.findall(text)}
    if "Name" not in attrs:
        return None
    dm = re.search(r'"""(.*?)"""', text, re.S)
    doc = dm.group(1) if dm else ""
    summary = " ".join(l.strip() for l in doc.split("-\n")[0].strip().splitlines()).strip()
    ins = [[n, n, d[:160]] for n, d in section(doc, "Args")]
    outs = [[n, n, d[:160]] for n, d in section(doc, "Returns")]
    return {"name": attrs["Name"], "nick": attrs.get("NickName"), "cat": attrs.get("Category", ""),
            "sub": attrs.get("SubCategory", ""), "desc": summary[:200], "in": ins, "out": outs,
            "version": attrs.get("Message", "")}


def main(src: str, dest: str) -> None:
    comps, versions = [], {}
    for pkg in sorted(Path(src).glob("*/*_grasshopper*/src")):
        for f in sorted(pkg.glob("*.py")):
            c = parse(f)
            if c is None:
                continue
            versions[c["cat"]] = max(versions.get(c["cat"], ""), c["version"])
            comps.append([c["name"], c["nick"], f'{c["cat"]} / {c["sub"]}', c["desc"], c["in"], c["out"]])
    order = ["Ladybug", "Honeybee", "HB-Radiance", "HB-Energy", "Dragonfly"]   # most used first
    comps.sort(key=lambda c: order.index(c[2].split(" / ")[0]) if c[2].split(" / ")[0] in order else 9)
    data = {"id": "ladybug", "name": "Ladybug Tools",
            "version_checked": ", ".join(f"{k} {v}" for k, v in sorted(versions.items()) if k),
            "source": "component sources in the ladybug-grasshopper, honeybee-grasshopper-* and "
                      "dragonfly-grasshopper packages on PyPI",
            "notes": "Inputs named _x are required, _x_ have a default, x_ are optional. Outputs "
                     "include a 'report' text output first. The third item of each parameter is "
                     "its documentation, not a type.",
            "components": comps}
    Path(dest, "ladybug.json").write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
    print(len(comps), "components;", data["version_checked"])


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
