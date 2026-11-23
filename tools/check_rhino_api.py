"""Check that every RhinoCommon / Grasshopper member the bridge and recipes use exists in Rhino 8.

Downloads the official RhinoCommon and Grasshopper NuGet packages (the same assemblies Rhino 8
ships), reads their metadata with `dnfile`, and looks up each `Type Member` line in
rhino_api_uses.txt, following base classes (including generic ones). "Member/N" also checks that
an overload accepts N arguments (counting optional parameters).

    pip install dnfile
    python tools/check_rhino_api.py            # uses ~/.cache/kazi-rhino/nuget
    python tools/check_rhino_api.py --version 8.36.26296.17001

Exit code 1 if anything is missing.
"""

from __future__ import annotations

import argparse
import io
import pathlib
import sys
import urllib.request
import zipfile

USES = pathlib.Path(__file__).with_name("rhino_api_uses.txt")
PACKAGES = {"rhinocommon": ["RhinoCommon.dll", "Rhino.UI.dll", "Eto.dll"],
            "grasshopper": ["Grasshopper.dll", "GH_IO.dll"]}
DEFAULT_VERSION = "8.36.26296.17001"


def fetch(cache: pathlib.Path, version: str) -> list[pathlib.Path]:
    dlls = []
    for pkg, names in PACKAGES.items():
        folder = cache / f"{pkg}.{version}"
        if not folder.exists():
            url = f"https://api.nuget.org/v3-flatcontainer/{pkg}/{version}/{pkg}.{version}.nupkg"
            print("downloading", url)
            data = urllib.request.urlopen(url, timeout=120).read()  # noqa: S310
            zipfile.ZipFile(io.BytesIO(data)).extractall(folder)
        lib = next(p for p in sorted((folder / "lib").iterdir()) if p.name.startswith("net") and p.name != "net48")
        dlls += [lib / n for n in names if (lib / n).exists()]
    return dlls


def _compressed(b: bytes, i: int) -> tuple[int, int]:
    if b[i] & 0x80 == 0:
        return b[i], i + 1
    if b[i] & 0xC0 == 0x80:
        return ((b[i] & 0x3F) << 8) | b[i + 1], i + 2
    return ((b[i] & 0x1F) << 24) | (b[i + 1] << 16) | (b[i + 2] << 8) | b[i + 3], i + 4


def index(dlls: list[pathlib.Path]) -> dict[str, dict]:
    import dnfile  # noqa: PLC0415

    types: dict[str, dict] = {}
    for path in dlls:
        pe = dnfile.dnPE(str(path))
        md = pe.net.mdtables
        rows = md.TypeDef.rows
        nested = {r.NestedClass.row_index: r.EnclosingClass.row_index for r in (md.NestedClass.rows if md.NestedClass else [])}

        def tname(i, rows=rows, nested=nested):
            r = rows[i - 1]
            if i in nested:
                return tname(nested[i]) + "+" + str(r.TypeName)
            ns = str(r.TypeNamespace)
            return (ns + "." if ns else "") + str(r.TypeName)

        def ref(row):
            ns = getattr(row, "TypeNamespace", None)
            return (str(ns) + "." if ns and str(ns) else "") + str(row.TypeName)

        def base(r, tname=tname):
            ext = r.Extends
            if ext is None or ext.row is None:
                return None
            if ext.table is not None and ext.table.name == "TypeSpec":
                b = bytes(ext.row.Signature.value)
                if len(b) > 2 and b[0] == 0x15:  # GENERICINST CLASS/VALUETYPE TypeDefOrRef
                    coded, _ = _compressed(b, 2)
                    tag, idx = coded & 3, coded >> 2
                    if tag == 0:
                        return tname(idx)
                    if tag == 1:
                        return ref(md.TypeRef.rows[idx - 1])
                return None
            if ext.table is not None and ext.table.name == "TypeDef":
                return tname(ext.row_index)
            return ref(ext.row)

        for i, r in enumerate(rows, 1):
            members = {str(m.row.Name) for m in r.MethodList} | {str(f.row.Name) for f in r.FieldList}
            arity: dict[str, list[tuple[int, int]]] = {}
            for m in r.MethodList:
                params = [p.row for p in m.row.ParamList if str(p.row.Name)]
                required = sum(1 for p in params if not p.Flags.pdOptional)
                arity.setdefault(str(m.row.Name), []).append((required, len(params)))
            types[tname(i)] = {"base": base(r), "members": members, "ifaces": [], "arity": arity}
        for pm in (md.PropertyMap.rows if md.PropertyMap else []):
            types[tname(pm.Parent.row_index)]["members"] |= {str(p.row.Name) for p in pm.PropertyList}
        for em in (md.EventMap.rows if md.EventMap else []):
            types[tname(em.Parent.row_index)]["members"] |= {str(e.row.Name) for e in em.EventList}
        for ii in (md.InterfaceImpl.rows if md.InterfaceImpl else []):
            iface = ii.Interface
            if iface.table is not None and iface.table.name in ("TypeDef", "TypeRef"):
                name = tname(iface.row_index) if iface.table.name == "TypeDef" else ref(iface.row)
                types[tname(ii.Class.row_index)]["ifaces"].append(name)
    return types


def has(types, t, m, seen=None, nargs=None) -> bool | None:
    """Member m exists on t or a base/interface. With nargs, some overload takes that many args."""
    seen = seen or set()
    if t not in types or t in seen:
        return None
    seen.add(t)
    info = types[t]
    if nargs is None and {m, "get_" + m, "set_" + m} & info["members"]:
        return True
    if nargs is not None and any(lo <= nargs <= hi for lo, hi in info["arity"].get(m, [])):
        return True
    for parent in [info["base"], *info["ifaces"]]:
        if parent and has(types, parent, m, seen, nargs):
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--version", default=DEFAULT_VERSION)
    ap.add_argument("--cache", default="~/.cache/kazi-rhino/nuget")
    ap.add_argument("--uses", default=str(USES))
    args = ap.parse_args()
    types = index(fetch(pathlib.Path(args.cache).expanduser(), args.version))
    problems = checked = 0
    for line in pathlib.Path(args.uses).read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        t, m = line.rsplit(" ", 1)
        nargs = None
        if "/" in m:  # "Member/2": an overload must accept exactly 2 arguments
            m, n = m.split("/")
            nargs = int(n)
        checked += 1
        ok = has(types, t, m, nargs=nargs)
        if ok is not True:
            problems += 1
            what = f"{m}/{nargs}" if nargs is not None else m
            print(("unknown type   " if ok is None else "missing member ") + f"{t} :: {what}")
    print(f"{checked} API uses checked against Rhino {args.version}: {problems} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
