#! python3
# -*- coding: utf-8 -*-
"""
Add-on support for the kazi bridge: find, place and wire components from any installed
Grasshopper plug-in (LunchBox, Kangaroo 2, Weaverbird, Pufferfish, Elefront, Human, Wallacei,
Ladybug Tools, Hops, Speckle, ...).

rhino_ai_bridge.py loads this file by itself (it sits in the same folder) and calls
register(bridge), which adds the commands below to the bridge. Nothing here is specific to one
plug-in: components are looked up in Grasshopper's own component list at run time, so whatever
is installed on this machine is what gets used.

Runs inside Rhino 8 (CPython 3.9): keep the syntax 3.9-compatible.
"""

import re

VERSION = "0.1.0"

_PREFIXES = ("weaverbird's ", "weaverbird’s ", "wb ")


def norm(text):
    """Loose form of a component or parameter name: lower case, letters and digits only."""
    s = str(text or "").strip().lower()
    for prefix in _PREFIXES:
        if s.startswith(prefix):
            s = s[len(prefix):]
    return re.sub(r"[^a-z0-9]+", "", s)


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def register(b):
    """b: the bridge module (or a namespace with its globals). Returns the new commands."""
    import System  # noqa: PLC0415  (only inside Rhino)

    on_ui = b.on_ui
    state = {"index": None, "count": -1}

    # ------------------------------------------------------------------ #
    # index of everything Grasshopper has loaded
    # ------------------------------------------------------------------ #
    def libraries():
        gh = b._gh()
        libs = {}
        try:
            for lib in gh.Instances.ComponentServer.Libraries:
                libs[str(lib.Id)] = lib
        except Exception:  # noqa: BLE001
            pass
        return libs

    def proxy_entry(proxy, libs):
        desc = proxy.Desc
        lib = libs.get(str(getattr(proxy, "LibraryGuid", "")))
        return {
            "proxy": proxy,
            "name": str(desc.Name),
            "nickname": str(desc.NickName),
            "category": str(getattr(desc, "Category", "") or ""),
            "subcategory": str(getattr(desc, "SubCategory", "") or ""),
            "description": str(getattr(desc, "Description", "") or ""),
            "guid": str(getattr(proxy, "Guid", "") or ""),
            "library": str(lib.Name) if lib is not None else "",
            "kind": str(getattr(proxy, "Kind", "") or ""),
            "obsolete": bool(proxy.Obsolete),
            "n_name": norm(desc.Name),
            "n_nick": norm(desc.NickName),
        }

    def index():
        gh = b._gh()
        proxies = list(gh.Instances.ComponentServer.ObjectProxies)
        if state["index"] is None or state["count"] != len(proxies):
            libs = libraries()
            state["index"] = [proxy_entry(p, libs) for p in proxies]
            state["count"] = len(proxies)
        return state["index"]

    def public(entry, score=None):
        out = {k: entry[k] for k in ("name", "nickname", "category", "subcategory", "description",
                                     "guid", "library", "kind")}
        if entry["obsolete"]:
            out["obsolete"] = True
        if score is not None:
            out["score"] = score
        return out

    def belongs(entry, categories, libs):
        """Does this component come from the plug-in described by these tab / library names?"""
        cat, sub, lib = norm(entry["category"]), norm(entry["subcategory"]), norm(entry["library"])
        for c in categories:
            c = norm(c)
            if c and (c == cat or sub.startswith(c) or (len(c) > 3 and (c in cat or c in sub))):
                return True
        for name in libs:
            name = norm(name)
            if name and name in lib:
                return True
        return False

    # ------------------------------------------------------------------ #
    # resolving a wanted component to an installed one
    # ------------------------------------------------------------------ #
    def score(entry, wanted):
        best = 0
        for w in wanted:
            if not w:
                continue
            if w == entry["n_name"]:
                best = max(best, 100)
            elif w == entry["n_nick"]:
                best = max(best, 92)
            elif len(w) >= 4 and entry["n_name"].startswith(w):
                best = max(best, 60)
            elif len(w) >= 4 and w in entry["n_name"]:
                best = max(best, 45)
            elif len(w) >= 4 and w in entry["n_nick"]:
                best = max(best, 35)
        return best

    def resolve(spec, minimum=90):
        """spec: {"name" or "names", "guid", "categories", "libraries"} -> (entry, score, others).

        Exact name or nickname matches win; a component from the wanted plug-in beats a
        same-named one from elsewhere ("Solver", "Hex", "Offset Mesh" exist in several).
        """
        if isinstance(spec, str):
            spec = {"name": spec}
        entries = index()
        guid = str(spec.get("guid") or "").lower()
        if guid:
            for e in entries:
                if e["guid"].lower() == guid:
                    return e, 100, []
        wanted = [norm(n) for n in _as_list(spec.get("names")) + _as_list(spec.get("name"))]
        categories = _as_list(spec.get("categories")) + _as_list(spec.get("category"))
        libs = _as_list(spec.get("libraries")) + _as_list(spec.get("library"))
        scoped = bool(categories or libs)
        ranked = []
        for e in entries:
            if e["obsolete"] and not spec.get("include_obsolete"):
                continue
            s = score(e, wanted)
            if not s:
                continue
            if scoped:
                s += 20 if belongs(e, categories, libs) else -30
            ranked.append((s, e))
        ranked.sort(key=lambda pair: (-pair[0], pair[1]["name"]))
        floor = int(spec.get("min_score", minimum))
        if not ranked or ranked[0][0] < floor:
            return None, 0, [public(e, s) for s, e in ranked[:5]]
        top_score, top = ranked[0]
        others = [public(e, s) for s, e in ranked[1:4] if s >= top_score - 10]
        return top, top_score, others

    def not_found(spec, near):
        names = _as_list(spec.get("names")) + _as_list(spec.get("name")) if isinstance(spec, dict) else [spec]
        where = ""
        if isinstance(spec, dict):
            scope = _as_list(spec.get("categories")) + _as_list(spec.get("category"))
            if scope:
                where = " in %s" % "/".join(str(s) for s in scope)
        hint = ""
        if near:
            hint = " Closest: " + ", ".join("%s [%s]" % (n["name"], n["category"]) for n in near)
        return "No Grasshopper component named %s%s is installed.%s" % (
            " / ".join("'%s'" % n for n in names), where, hint)

    # ------------------------------------------------------------------ #
    # parameters
    # ------------------------------------------------------------------ #
    def param_info(p):
        info = {"name": str(p.Name), "nickname": str(p.NickName)}
        for key, attr in (("type", "TypeName"), ("access", "Access"), ("description", "Description")):
            try:
                info[key] = str(getattr(p, attr))
            except Exception:  # noqa: BLE001
                pass
        try:
            info["optional"] = bool(p.Optional)
        except Exception:  # noqa: BLE001
            pass
        return info

    def params_of(obj, side):
        return b._param_list(obj, side)

    def match_param(obj, side, refs):
        """Find a parameter by any of several names / nicknames / indexes, loosely."""
        params = params_of(obj, side)
        refs = _as_list(refs)
        if not refs:
            if not params:
                raise ValueError("%s has no %s parameters" % (obj.NickName, side))
            return params[0]
        for ref in refs:  # exact first
            if isinstance(ref, int) and not isinstance(ref, bool):
                if 0 <= ref < len(params):
                    return params[ref]
                continue
            low = str(ref).lower()
            for p in params:
                if str(p.NickName).lower() == low or str(p.Name).lower() == low:
                    return p
        for ref in refs:  # then loose
            if isinstance(ref, int):
                continue
            n = norm(ref)
            for p in params:
                if n and (norm(p.NickName) == n or norm(p.Name) == n):
                    return p
        for ref in refs:  # then a digit string as an index
            if isinstance(ref, str) and ref.isdigit() and int(ref) < len(params):
                return params[int(ref)]
        raise ValueError("%s has no %s named %s (it has: %s)" % (
            obj.NickName, side, " / ".join("'%s'" % r for r in refs),
            ", ".join("%s (%s)" % (p.Name, p.NickName) for p in params) or "none"))

    def goo_for(param, value):
        types = b._gh().Kernel.Types
        kind = param.GetType().Name
        if isinstance(value, bool) or kind == "Param_Boolean":
            if isinstance(value, str):
                value = value.strip().lower() in ("true", "yes", "1", "on")
            return types.GH_Boolean(bool(value))
        if kind == "Param_Integer":
            return types.GH_Integer(int(round(float(value))))
        if kind == "Param_Number":
            return types.GH_Number(float(value))
        if kind in ("Param_String", "Param_FilePath"):
            return types.GH_String(str(value))
        if isinstance(value, int):
            return types.GH_Integer(value)
        if isinstance(value, float):
            return types.GH_Number(value)
        return types.GH_String(str(value))

    def set_persistent(param, value):
        if not hasattr(param, "PersistentData"):
            raise ValueError("'%s' can't hold a value of its own (script-based component). "
                             "Wire a slider, toggle or panel into it instead." % param.NickName)
        values = _as_list(value)
        param.RemoveAllSources()
        param.PersistentData.Clear()
        for v in values:
            param.PersistentData.Append(goo_for(param, v))
        param.ExpireSolution(False)
        return len(values)

    def apply_mapping(param, mapping):
        if not mapping:
            return
        gh = b._gh()
        modes = {"flatten": gh.Kernel.GH_DataMapping.Flatten, "graft": gh.Kernel.GH_DataMapping.Graft,
                 "none": getattr(gh.Kernel.GH_DataMapping, "None")}
        key = str(mapping).lower()
        if key not in modes:
            raise ValueError("mapping must be flatten, graft or none")
        param.DataMapping = modes[key]

    # ------------------------------------------------------------------ #
    # commands
    # ------------------------------------------------------------------ #
    def cmd_gh_plugins(args):
        """Installed Grasshopper libraries and ribbon tabs, with component counts."""
        def work():
            entries = index()
            per_lib, per_cat = {}, {}
            for e in entries:
                if e["obsolete"]:
                    continue
                per_lib[e["library"]] = per_lib.get(e["library"], 0) + 1
                per_cat[e["category"]] = per_cat.get(e["category"], 0) + 1
            libs = []
            for lib in libraries().values():
                item = {"name": str(lib.Name), "components": per_lib.get(str(lib.Name), 0)}
                for key, attr in (("version", "Version"), ("author", "AuthorName"), ("location", "Location")):
                    try:
                        item[key] = str(getattr(lib, attr) or "")
                    except Exception:  # noqa: BLE001
                        pass
                try:
                    item["core"] = bool(lib.IsCoreLibrary)
                except Exception:  # noqa: BLE001
                    pass
                libs.append(item)
            libs.sort(key=lambda i: i["name"].lower())
            return {"libraries": libs, "categories": dict(sorted(per_cat.items())),
                    "components": len(entries), "addons_bridge": VERSION}
        return on_ui(work)

    def cmd_gh_search_components(args):
        """Search installed components by words in the name, nickname or description."""
        query = str(args.get("query") or "")
        words = [norm(w) for w in re.split(r"\s+", query) if norm(w)]
        whole = norm(query)
        categories = _as_list(args.get("categories")) + _as_list(args.get("category"))
        libs = _as_list(args.get("libraries")) + _as_list(args.get("library"))
        limit = int(args.get("limit", 20))

        def work():
            hits = []
            for e in index():
                if e["obsolete"] and not args.get("include_obsolete"):
                    continue
                if (categories or libs) and not belongs(e, categories, libs):
                    continue
                s = score(e, [whole]) if whole else 1
                if words and not s:
                    hay_name = e["n_name"] + " " + e["n_nick"]
                    hay_desc = norm(e["description"]) + norm(e["subcategory"])
                    in_name = sum(1 for w in words if w in hay_name)
                    in_desc = sum(1 for w in words if w in hay_desc)
                    if in_name + in_desc < len(words):
                        continue
                    s = 10 + 5 * in_name
                if s:
                    hits.append((s, e))
            hits.sort(key=lambda pair: (-pair[0], pair[1]["category"], pair[1]["name"]))
            out = []
            for s, e in hits[:limit]:
                item = public(e, s)
                if args.get("with_params"):
                    item.update(instance_params(e))
                out.append(item)
            return {"count": len(hits), "components": out}
        return on_ui(work)

    def instance_params(entry):
        """Create the component off-canvas just to read its parameters."""
        try:
            obj = entry["proxy"].CreateInstance()
        except Exception as exc:  # noqa: BLE001
            return {"params_error": str(exc)}
        if obj is None:
            return {"params_error": "could not create an instance"}
        if hasattr(obj, "Params"):
            return {"inputs": [param_info(p) for p in obj.Params.Input],
                    "outputs": [param_info(p) for p in obj.Params.Output]}
        return {"inputs": [], "outputs": [param_info(obj)], "floating_param": True}

    def cmd_gh_component_info(args):
        """Exact inputs and outputs of an installed component, without placing it."""
        def work():
            entry, s, others = resolve(args)
            if entry is None:
                raise ValueError(not_found(args, others))
            info = public(entry, s)
            info.update(instance_params(entry))
            if others:
                info["alternatives"] = others
            return info
        return on_ui(work)

    def cmd_gh_resolve(args):
        """Check a list of wanted components against what is installed. Places nothing."""
        def work():
            out = []
            for spec in args.get("components") or []:
                entry, s, others = resolve(spec)
                if entry is None:
                    out.append({"found": False, "wanted": spec, "closest": others})
                else:
                    item = public(entry, s)
                    item["found"] = True
                    if args.get("with_params"):
                        item.update(instance_params(entry))
                    out.append(item)
            return {"components": out, "missing": sum(1 for o in out if not o["found"])}
        return on_ui(work)

    def cmd_gh_place(args):
        """Place a component from any plug-in. Like gh_add_component, but takes several
        candidate names, a GUID, and the plug-in's tab / library names to pick the right one."""
        def work():
            doc = b._gh_doc()
            entry, s, others = resolve(args)
            if entry is None:
                raise ValueError(not_found(args, others))
            obj = entry["proxy"].CreateInstance()
            if obj is None:
                raise RuntimeError("Grasshopper could not create '%s'" % entry["name"])
            b._place(doc, obj, args.get("x", 100), args.get("y", 100))
            if args.get("nickname"):
                obj.NickName = args["nickname"]
            problems = []
            for ref, value in (args.get("set") or {}).items():
                try:
                    set_persistent(match_param(obj, "input", [ref]), value)
                except Exception as exc:  # noqa: BLE001
                    problems.append(str(exc))
            info = b._describe(obj)
            info["resolved"] = public(entry, s)
            if others:
                info["alternatives"] = others
            if problems:
                info["problems"] = problems
            return info
        return on_ui(work)

    def cmd_gh_wire(args):
        """Wire source -> target. Parameters may be given as a list of possible names,
        matched loosely. mapping: "flatten" | "graft" on the target input."""
        def work():
            doc = b._gh_doc()
            src = b._find_obj(doc, args["source"])
            dst = b._find_obj(doc, args["target"])
            out_p = match_param(src, "output", args.get("source_output"))
            in_p = match_param(dst, "input", args.get("target_input"))
            if not args.get("keep_existing", True):
                in_p.RemoveAllSources()
            in_p.AddSource(out_p)
            apply_mapping(in_p, args.get("mapping"))
            dst.ExpireSolution(False)
            return {"connected": "%s.%s -> %s.%s" % (src.NickName, out_p.NickName, dst.NickName, in_p.NickName),
                    "source_output": str(out_p.NickName), "target_input": str(in_p.NickName)}
        return on_ui(work)

    def cmd_gh_set_input(args):
        """Type a value (number, true/false, text, or a list) straight into a component input."""
        def work():
            doc = b._gh_doc()
            obj = b._find_obj(doc, args["component"])
            p = match_param(obj, "input", args.get("input"))
            n = set_persistent(p, args.get("value"))
            apply_mapping(p, args.get("mapping"))
            return {"component": str(obj.NickName), "input": str(p.NickName), "values": n}
        return on_ui(work)

    def cmd_gh_add_panel(args):
        def work():
            gh = b._gh()
            doc = b._gh_doc()
            panel = gh.Kernel.Special.GH_Panel()
            b._place(doc, panel, args.get("x", 100), args.get("y", 100))
            panel.NickName = args.get("nickname") or "note"
            panel.UserText = str(args.get("text") or "")
            panel.ExpireSolution(False)
            return b._describe(panel)
        return on_ui(work)

    def cmd_gh_inspect(args):
        """Parameters, wires, runtime messages and a data preview of anything on the canvas."""
        def work():
            return b._describe(b._find_obj(b._gh_doc(), args["component"]), with_data=True)
        return on_ui(work)

    def cmd_gh_delete_many(args):
        def work():
            doc = b._gh_doc()
            removed = 0
            for ref in args.get("components") or []:
                try:
                    doc.RemoveObject(b._find_obj(doc, ref), False)
                    removed += 1
                except ValueError:
                    pass
            doc.NewSolution(False)
            return {"removed": removed}
        return on_ui(work)

    def cmd_gh_hops_set_path(args):
        """Point a Hops component at a .gh file or a URL; its inputs and outputs then appear."""
        def work():
            doc = b._gh_doc()
            obj = b._find_obj(doc, args["component"])
            if not hasattr(obj, "RemoteDefinitionLocation"):
                raise ValueError("%s is not a Hops component" % obj.NickName)
            obj.RemoteDefinitionLocation = str(args["path"])
            obj.ExpireSolution(False)
            return b._describe(obj)
        return on_ui(work)

    def cmd_gh_component_dump(args):
        """A page of the installed component list (for saving a local catalog)."""
        offset, limit = int(args.get("offset", 0)), int(args.get("limit", 200))
        categories = _as_list(args.get("categories"))
        libs = _as_list(args.get("libraries"))

        def work():
            entries = [e for e in index() if not e["obsolete"]
                       and (not (categories or libs) or belongs(e, categories, libs))]
            page = []
            for e in entries[offset:offset + limit]:
                item = public(e)
                if args.get("with_params"):
                    item.update(instance_params(e))
                page.append(item)
            return {"total": len(entries), "offset": offset, "components": page}
        return on_ui(work)

    commands = {
        "gh_plugins": cmd_gh_plugins,
        "gh_search_components": cmd_gh_search_components,
        "gh_component_info": cmd_gh_component_info,
        "gh_resolve": cmd_gh_resolve,
        "gh_place": cmd_gh_place,
        "gh_wire": cmd_gh_wire,
        "gh_set_input": cmd_gh_set_input,
        "gh_add_panel": cmd_gh_add_panel,
        "gh_inspect": cmd_gh_inspect,
        "gh_delete_many": cmd_gh_delete_many,
        "gh_hops_set_path": cmd_gh_hops_set_path,
        "gh_component_dump": cmd_gh_component_dump,
    }
    b.COMMANDS.update(commands)
    return commands
