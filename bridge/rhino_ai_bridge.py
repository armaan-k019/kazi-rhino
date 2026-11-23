#! python3
# -*- coding: utf-8 -*-
"""
rhino-ai-mods bridge for Rhino 8.

Run this inside Rhino 8 (Python 3 / CPython). It starts a small TCP server on
127.0.0.1:2010 that the rhino-ai-mods MCP server and the voice pipeline talk to.

    Rhino command line:   _-ScriptEditor _Run "C:\\path\\to\\rhino_ai_bridge.py"

Running it again restarts the server. Stop it with:  _-ScriptEditor _Run "...\\stop_bridge.py"

Protocol: one JSON object per line.
    request : {"id": 1, "cmd": "ping", "args": {}}
    response: {"id": 1, "ok": true, "result": ...}   or   {"id": 1, "ok": false, "error": "..."}

Everything that touches Rhino or Grasshopper is marshalled onto Rhino's UI thread.
"""

import json
import socket
import threading
import traceback

import System
import Rhino
import scriptcontext as sc

HOST = "127.0.0.1"
PORT = 2010
STICKY_KEY = "rhino_ai_mods_bridge"
COMMANDS_KEY = "rhino_ai_mods_commands"
BUILDS_KEY = "kazi_builds"
VERSION = "0.3.0"
UI_TIMEOUT_MS = 60000
APPEND = 2147483647  # GH_Document.AddObject index: end of the object list


# --------------------------------------------------------------------------- #
# UI-thread helper
# --------------------------------------------------------------------------- #

def on_ui(func, timeout_ms=UI_TIMEOUT_MS):
    """Run func() on Rhino's UI thread and return its result (or raise its error)."""
    if Rhino.RhinoApp.IsOnMainThread:
        # Called from a script running inside Rhino (e.g. the Kazi* commands): run directly,
        # waiting for ourselves would deadlock.
        return func()
    box = {}
    done = System.Threading.ManualResetEvent(False)

    def runner():
        try:
            box["result"] = func()
        except Exception as exc:  # noqa: BLE001
            box["error"] = exc
            box["tb"] = traceback.format_exc()
        finally:
            done.Set()

    Rhino.RhinoApp.InvokeOnUiThread(System.Action(runner))
    if not done.WaitOne(timeout_ms):
        raise RuntimeError("Timed out waiting for Rhino's UI thread (is a command or dialog open?)")
    if "error" in box:
        raise RuntimeError("%s\n%s" % (box["error"], box.get("tb", "")))
    return box.get("result")


# --------------------------------------------------------------------------- #
# Rhino commands
# --------------------------------------------------------------------------- #

def cmd_ping(args):
    return {
        "bridge": VERSION,
        "rhino": str(Rhino.RhinoApp.Version),
        "document": on_ui(lambda: (Rhino.RhinoDoc.ActiveDoc.Name or "(untitled)") if Rhino.RhinoDoc.ActiveDoc else None),
        "grasshopper_open": on_ui(lambda: _gh_canvas(open_if_needed=False) is not None),
    }


def cmd_run_command(args):
    """Run a Rhino macro.

    mode="keystrokes" (default) types the macro into the command line, like a person would.
        It returns immediately, so interactive commands (pick points etc.) work.
        enter=False leaves it in the command line for the user to confirm with Enter.
    mode="script" runs it with RhinoApp.RunScript and waits for it to finish.
    """
    macro = (args.get("macro") or "").strip()
    if not macro and not args.get("allow_empty"):
        raise ValueError("macro is required (pass allow_empty=true to just press Enter)")
    mode = args.get("mode", "keystrokes")
    enter = bool(args.get("enter", True))
    echo = bool(args.get("echo", True))

    if mode == "script":
        ok = on_ui(lambda: Rhino.RhinoApp.RunScript(macro, echo))
        return {"ran": bool(ok), "macro": macro, "mode": mode}

    def type_it():
        text = macro
        # "!" at the start of a macro cancels whatever command is running.
        if args.get("cancel_running", True) and Rhino.Commands.Command.InCommand() and not text.startswith("!"):
            text = "! " + text
        Rhino.RhinoApp.SendKeystrokes(text, enter)
        return True

    on_ui(type_it)
    return {"typed": True, "macro": macro, "enter": enter, "mode": mode}


def cmd_list_rhino_commands(args):
    def names():
        english = Rhino.Commands.Command.GetCommandNames(True, bool(args.get("loaded_only", False)))
        return sorted(set(str(n) for n in english))
    return {"commands": on_ui(names)}


# --------------------------------------------------------------------------- #
# Grasshopper helpers
# --------------------------------------------------------------------------- #

def _gh():
    import Grasshopper  # noqa: WPS433  (only importable once GH is loaded)
    return Grasshopper


def _gh_canvas(open_if_needed=True):
    try:
        gh = _gh()
    except Exception:  # noqa: BLE001
        gh = None
    canvas = gh.Instances.ActiveCanvas if gh else None
    if canvas is None and open_if_needed:
        Rhino.RhinoApp.RunScript("_-Grasshopper _Window _Show _Enter", False)
        gh = _gh()
        canvas = gh.Instances.ActiveCanvas
    return canvas


def _gh_doc(create=True):
    gh = _gh()
    canvas = _gh_canvas()
    if canvas is None:
        raise RuntimeError("Grasshopper is not open. Run the Grasshopper command in Rhino first.")
    doc = canvas.Document
    if doc is None and create:
        doc = gh.Kernel.GH_Document()
        gh.Instances.DocumentServer.AddDocument(doc)
        canvas.Document = doc
    return doc


def _find_proxy(name):
    gh = _gh()
    wanted = name.strip().lower()
    exact, partial = [], []
    for proxy in gh.Instances.ComponentServer.ObjectProxies:
        if proxy.Obsolete:
            continue
        desc = proxy.Desc
        names = [str(desc.Name).lower(), str(desc.NickName).lower()]
        if wanted in names:
            exact.append(proxy)
        elif any(wanted in n for n in names):
            partial.append(proxy)
    found = exact or partial
    if not found:
        raise ValueError("No Grasshopper component named '%s'" % name)
    return found[0]


def _place(doc, obj, x, y):
    obj.CreateAttributes()
    if x is not None and y is not None:
        obj.Attributes.Pivot = System.Drawing.PointF(float(x), float(y))
    doc.AddObject(obj, False, APPEND)
    return obj


def _find_obj(doc, ref):
    """Find a canvas object by InstanceGuid, or by NickName/Name (first match)."""
    if not ref:
        raise ValueError("component reference is required")
    try:
        obj = doc.FindObject(System.Guid(str(ref)), True)
        if obj is not None:
            return obj
    except Exception:  # noqa: BLE001
        pass
    low = str(ref).lower()
    for obj in doc.Objects:
        if str(obj.NickName).lower() == low:
            return obj
    for obj in doc.Objects:
        if str(obj.Name).lower() == low:
            return obj
    raise ValueError("No component '%s' on the canvas" % ref)


def _param_list(obj, side):
    if hasattr(obj, "Params"):
        return list(obj.Params.Input if side == "input" else obj.Params.Output)
    return [obj]  # a floating parameter (slider, panel, ...) is its own input and output


def _find_param(obj, side, ref):
    params = _param_list(obj, side)
    if ref is None or ref == "":
        if not params:
            raise ValueError("%s has no %s parameters" % (obj.NickName, side))
        return params[0]
    if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
        return params[int(ref)]
    low = str(ref).lower()
    for p in params:
        if str(p.NickName).lower() == low or str(p.Name).lower() == low:
            return p
    raise ValueError("%s has no %s named '%s' (has: %s)" % (
        obj.NickName, side, ref, ", ".join(str(p.NickName) for p in params)))


def _messages(obj):
    gh = _gh()
    out = []
    levels = (("error", gh.Kernel.GH_RuntimeMessageLevel.Error),
              ("warning", gh.Kernel.GH_RuntimeMessageLevel.Warning),
              ("remark", gh.Kernel.GH_RuntimeMessageLevel.Remark))
    for label, level in levels:
        try:
            for msg in obj.RuntimeMessages(level):
                out.append({"level": label, "text": str(msg)})
        except Exception:  # noqa: BLE001
            pass
    return out


def _describe(obj, with_data=False):
    info = {
        "guid": str(obj.InstanceGuid),
        "name": str(obj.Name),
        "nickname": str(obj.NickName),
        "type": obj.GetType().FullName,
        "x": float(obj.Attributes.Pivot.X) if obj.Attributes else None,
        "y": float(obj.Attributes.Pivot.Y) if obj.Attributes else None,
        "messages": _messages(obj),
    }
    if hasattr(obj, "Params"):
        info["inputs"] = [_describe_param(p, with_data) for p in obj.Params.Input]
        info["outputs"] = [_describe_param(p, with_data) for p in obj.Params.Output]
    else:
        info["param"] = _describe_param(obj, with_data)
    if _is_script(obj):
        info["is_script"] = True
    return info


def _describe_param(p, with_data=False):
    d = {
        "name": str(p.Name),
        "nickname": str(p.NickName),
        "access": str(p.Access),
        "sources": [{"component": str(s.Attributes.GetTopLevel.DocObject.InstanceGuid),
                     "param": str(s.NickName)} for s in p.Sources],
    }
    if with_data:
        try:
            vd = p.VolatileData
            d["data_count"] = int(vd.DataCount)
            d["data_preview"] = [str(g) for g in list(vd.AllData(True))[:20]]
        except Exception:  # noqa: BLE001
            pass
    return d


# --------------------------------------------------------------------------- #
# Script components
# --------------------------------------------------------------------------- #

SCRIPT_COMPONENTS = {
    # language -> candidate component names, newest first
    "python": ["Python 3 Script", "GhPython Script"],
    "python3": ["Python 3 Script"],
    "ironpython": ["IronPython 2 Script", "GhPython Script"],
    "csharp": ["C# Script"],
    "c#": ["C# Script"],
}

_MARSH_FLAGS = ("MarshInputs", "MarshOutputs", "MarshGuids")


def _is_script(obj):
    t = obj.GetType().FullName
    return "RhinoCodePluginGH" in t or "GhPython" in t or hasattr(obj, "SetSource") or hasattr(obj, "Code")


def _marsh_get(obj):
    """Rhino 8 script components lose their marshalling flags on SetSource; read them first."""
    flags = System.Reflection.BindingFlags
    decl = flags.Public | flags.NonPublic | flags.Instance | flags.DeclaredOnly
    vals = {}
    for short in _MARSH_FLAGS:
        name = "RhinoCodePlatform.GH.IScriptComponent." + short
        ty = obj.GetType()
        while ty is not None:
            prop = ty.GetProperty(name, decl)
            if prop is not None:
                try:
                    vals[short] = prop.GetValue(obj)
                except Exception:  # noqa: BLE001
                    pass
                break
            ty = ty.BaseType
    return vals


def _marsh_set(obj, vals):
    flags = System.Reflection.BindingFlags
    decl = flags.Public | flags.NonPublic | flags.Instance | flags.DeclaredOnly
    for short, val in vals.items():
        name = "RhinoCodePlatform.GH.IScriptComponent." + short
        ty = obj.GetType()
        while ty is not None:
            prop = ty.GetProperty(name, decl)
            if prop is not None and prop.CanWrite:
                try:
                    prop.SetValue(obj, val)
                except Exception:  # noqa: BLE001
                    pass
                break
            ty = ty.BaseType


def _get_source(obj):
    if hasattr(obj, "TryGetSource"):
        try:
            ok, text = obj.TryGetSource()
            if ok:
                return str(text)
        except Exception:  # noqa: BLE001
            pass
    for attr in ("Code", "ScriptSource"):
        if hasattr(obj, attr):
            val = getattr(obj, attr)
            # legacy C# component keeps a ScriptSource object
            return str(getattr(val, "ScriptCode", val))
    return None


def _set_source(obj, code):
    if hasattr(obj, "SetSource"):          # Rhino 8 Python 3 / C# / IronPython components
        obj.SetSource(code)
        return "SetSource"
    if hasattr(obj, "Code"):               # legacy GhPython
        obj.Code = code
        return "Code"
    raise RuntimeError("Don't know how to set code on %s" % obj.GetType().FullName)


def _access(value):
    gh = _gh()
    value = (value or "item").lower()
    return {"item": gh.Kernel.GH_ParamAccess.item,
            "list": gh.Kernel.GH_ParamAccess.list,
            "tree": gh.Kernel.GH_ParamAccess.tree}[value]


def _set_params(obj, side, specs):
    """Make a script component's inputs/outputs match `specs`.

    specs: list of names, or of {"name": str, "access": "item"|"list"|"tree", "description": str}.
    The Rhino 8 standard-output parameter ("out") is left alone.
    """
    if specs is None:
        return
    gh = _gh()
    kernel = gh.Kernel
    gh_side = kernel.GH_ParameterSide.Input if side == "input" else kernel.GH_ParameterSide.Output
    var = kernel.IGH_VariableParameterComponent(obj)
    specs = [{"name": s} if isinstance(s, str) else dict(s) for s in specs]

    def current():
        return list(obj.Params.Input if side == "input" else obj.Params.Output)

    keep_out = [p for p in current() if side == "output" and str(p.NickName) == "out"]
    editable = [p for p in current() if p not in keep_out]
    offset = len(keep_out) if (side == "output" and keep_out and obj.Params.Output.IndexOf(keep_out[0]) == 0) else 0

    # remove extras
    for p in editable[len(specs):]:
        if side == "input":
            obj.Params.UnregisterInputParameter(p, True)
        else:
            obj.Params.UnregisterOutputParameter(p, True)
    # add missing
    for i in range(len(editable), len(specs)):
        index = offset + i
        if not var.CanInsertParameter(gh_side, index):
            raise RuntimeError("Component does not allow adding a %s at %d" % (side, index))
        p = var.CreateParameter(gh_side, index)
        if side == "input":
            obj.Params.RegisterInputParam(p, index)
        else:
            obj.Params.RegisterOutputParam(p, index)
    # rename / configure
    params = [p for p in current() if p not in keep_out]
    for p, spec in zip(params, specs):
        p.Name = spec["name"]
        p.NickName = spec["name"]
        if spec.get("description"):
            p.Description = spec["description"]
        if side == "input" and spec.get("access"):
            p.Access = _access(spec["access"])
        if side == "input" and "optional" in spec:
            p.Optional = bool(spec["optional"])
    var.VariableParameterMaintenance()
    obj.Params.OnParametersChanged()


def _recompute(doc, obj):
    try:
        obj.ClearData()
    except Exception:  # noqa: BLE001
        pass
    obj.ExpireSolution(False)
    doc.NewSolution(False)
    canvas = _gh_canvas(open_if_needed=False)
    if canvas is not None:
        canvas.Refresh()


def _apply_script(doc, obj, code=None, inputs=None, outputs=None, nickname=None, recompute=True):
    marsh = _marsh_get(obj)
    _set_params(obj, "input", inputs)
    _set_params(obj, "output", outputs)
    setter = None
    if code is not None:
        setter = _set_source(obj, code)
    if marsh:
        _marsh_set(obj, marsh)
    if nickname:
        obj.NickName = nickname
    if recompute:
        _recompute(doc, obj)
    info = _describe(obj, with_data=True)
    info["setter"] = setter
    info["errors"] = [m for m in info["messages"] if m["level"] == "error"]
    info["success"] = not info["errors"]
    return info


def cmd_gh_create_script(args):
    language = (args.get("language") or "python").lower()
    candidates = SCRIPT_COMPONENTS.get(language)
    if not candidates:
        raise ValueError("language must be one of: %s" % ", ".join(SCRIPT_COMPONENTS))

    def work():
        doc = _gh_doc()
        proxy, last_err = None, None
        for name in candidates:
            try:
                proxy = _find_proxy(name)
                break
            except ValueError as exc:
                last_err = exc
        if proxy is None:
            raise last_err
        obj = proxy.CreateInstance()
        _place(doc, obj, args.get("x", 100), args.get("y", 100))
        return _apply_script(doc, obj, code=args.get("code", ""), inputs=args.get("inputs"),
                             outputs=args.get("outputs"), nickname=args.get("nickname"),
                             recompute=args.get("recompute", True))
    return on_ui(work)


def cmd_gh_update_script(args):
    def work():
        doc = _gh_doc()
        obj = _find_obj(doc, args.get("component"))
        if not _is_script(obj):
            raise ValueError("%s is not a script component" % obj.NickName)
        return _apply_script(doc, obj, code=args.get("code"), inputs=args.get("inputs"),
                             outputs=args.get("outputs"), nickname=args.get("nickname"),
                             recompute=args.get("recompute", True))
    return on_ui(work)


def cmd_gh_read_script(args):
    def work():
        obj = _find_obj(_gh_doc(), args.get("component"))
        info = _describe(obj, with_data=True)
        info["code"] = _get_source(obj)
        return info
    return on_ui(work)


# --------------------------------------------------------------------------- #
# Generic Grasshopper canvas commands
# --------------------------------------------------------------------------- #

def cmd_gh_list(args):
    def work():
        doc = _gh_doc()
        flt = (args.get("filter") or "").lower()
        items = []
        for obj in doc.Objects:
            if flt and flt not in str(obj.NickName).lower() and flt not in str(obj.Name).lower():
                continue
            items.append(_describe(obj, with_data=bool(args.get("with_data"))))
        return {"count": len(items), "objects": items}
    return on_ui(work)


def cmd_gh_add_component(args):
    def work():
        doc = _gh_doc()
        obj = _find_proxy(args["name"]).CreateInstance()
        _place(doc, obj, args.get("x", 100), args.get("y", 100))
        if args.get("nickname"):
            obj.NickName = args["nickname"]
        return _describe(obj)
    return on_ui(work)


def cmd_gh_connect(args):
    def work():
        doc = _gh_doc()
        src = _find_obj(doc, args["source"])
        dst = _find_obj(doc, args["target"])
        out_p = _find_param(src, "output", args.get("source_output"))
        in_p = _find_param(dst, "input", args.get("target_input"))
        if not args.get("keep_existing", True):
            in_p.RemoveAllSources()
        in_p.AddSource(out_p)
        dst.ExpireSolution(True)
        return {"connected": "%s.%s -> %s.%s" % (src.NickName, out_p.NickName, dst.NickName, in_p.NickName)}
    return on_ui(work)


def cmd_gh_disconnect(args):
    def work():
        doc = _gh_doc()
        dst = _find_obj(doc, args["target"])
        in_p = _find_param(dst, "input", args.get("target_input"))
        in_p.RemoveAllSources()
        dst.ExpireSolution(True)
        return {"disconnected": "%s.%s" % (dst.NickName, in_p.NickName)}
    return on_ui(work)


def cmd_gh_delete(args):
    def work():
        doc = _gh_doc()
        obj = _find_obj(doc, args["component"])
        doc.RemoveObject(obj, True)
        return {"deleted": str(obj.InstanceGuid)}
    return on_ui(work)


def cmd_gh_solve(args):
    def work():
        doc = _gh_doc()
        doc.NewSolution(True)
        problems = []
        for obj in doc.Objects:
            msgs = _messages(obj)
            if msgs:
                problems.append({"guid": str(obj.InstanceGuid), "nickname": str(obj.NickName), "messages": msgs})
        return {"problems": problems}
    return on_ui(work)


# --------------------------------------------------------------------------- #
# Selection, confirmation, messages
# --------------------------------------------------------------------------- #

def cmd_get_selection(args):
    def work():
        doc = Rhino.RhinoDoc.ActiveDoc
        objs = list(doc.Objects.GetSelectedObjects(False, False)) if doc else []
        return {"count": len(objs),
                "objects": [{"id": str(o.Id), "type": o.Geometry.GetType().Name,
                             "layer": doc.Layers[o.Attributes.LayerIndex].FullPath,
                             "name": o.Attributes.Name} for o in objs[:50]]}
    return on_ui(work)


def cmd_confirm(args):
    """Ask the user Yes/No in a Rhino dialog. Returns {"ok": bool}."""
    title = args.get("title") or "kazi-rhino"
    message = args.get("message") or "Continue?"

    def work():
        res = Rhino.UI.Dialogs.ShowMessage(message, title, Rhino.UI.ShowMessageButton.YesNo,
                                           Rhino.UI.ShowMessageIcon.Question)
        return res == Rhino.UI.ShowMessageResult.Yes
    return {"ok": bool(on_ui(work, timeout_ms=600000))}


def cmd_rhino_message(args):
    text = str(args.get("text") or "")
    on_ui(lambda: Rhino.RhinoApp.WriteLine("[kazi] " + text))
    return {"shown": True}


# --------------------------------------------------------------------------- #
# Grasshopper inputs: sliders, toggles, geometry from the Rhino selection
# --------------------------------------------------------------------------- #

def cmd_gh_add_slider(args):
    def work():
        gh = _gh()
        doc = _gh_doc()
        slider = gh.Kernel.Special.GH_NumberSlider()
        _place(doc, slider, args.get("x", 100), args.get("y", 100))
        integer = bool(args.get("integer"))
        lo, hi = float(args.get("min", 0)), float(args.get("max", 10))
        val = float(args.get("value", lo))
        if hi <= lo:
            hi = lo + 1
        val = min(max(val, lo), hi)
        s = slider.Slider
        s.Type = gh.GUI.Base.GH_SliderAccuracy.Integer if integer else gh.GUI.Base.GH_SliderAccuracy.Float
        s.DecimalPlaces = 0 if integer else int(args.get("decimals", 2))
        s.Minimum = System.Decimal(lo)
        s.Maximum = System.Decimal(hi)
        slider.SetSliderValue(System.Decimal(round(val) if integer else val))
        if args.get("nickname"):
            slider.NickName = args["nickname"]
        slider.ExpireSolution(False)
        return _describe(slider)
    return on_ui(work)


def cmd_gh_add_toggle(args):
    def work():
        gh = _gh()
        doc = _gh_doc()
        toggle = gh.Kernel.Special.GH_BooleanToggle()
        _place(doc, toggle, args.get("x", 100), args.get("y", 100))
        toggle.Value = bool(args.get("value", False))
        if args.get("nickname"):
            toggle.NickName = args["nickname"]
        return _describe(toggle)
    return on_ui(work)


def cmd_gh_add_geometry_input(args):
    """A Geometry parameter holding the objects currently selected in Rhino.

    reference=True (default) keeps a live link: editing the Rhino object updates Grasshopper.
    """
    def work():
        gh = _gh()
        doc = _gh_doc()
        param = gh.Kernel.Parameters.Param_Geometry()
        _place(doc, param, args.get("x", 100), args.get("y", 100))
        param.NickName = args.get("nickname") or "geometry"
        rdoc = Rhino.RhinoDoc.ActiveDoc
        objs = list(rdoc.Objects.GetSelectedObjects(False, False)) if (rdoc and args.get("from_selection", True)) else []
        added = 0
        for o in objs:
            goo = gh.Kernel.GH_Convert.ToGeometricGoo(o.Geometry)
            if goo is None:
                continue
            if args.get("reference", True):
                try:
                    goo.ReferenceID = o.Id
                    goo.LoadGeometry(rdoc)
                except Exception:  # noqa: BLE001  (fall back to an internalised copy)
                    goo = gh.Kernel.GH_Convert.ToGeometricGoo(o.Geometry)
            param.PersistentData.Append(goo)
            added += 1
        param.ExpireSolution(False)
        info = _describe(param)
        info["objects"] = added
        return info
    return on_ui(work)


def cmd_gh_group(args):
    def work():
        gh = _gh()
        doc = _gh_doc()
        grp = gh.Kernel.Special.GH_Group()
        grp.NickName = args.get("name") or "kazi"
        grp.CreateAttributes()
        for ref in args.get("components", []):
            grp.AddObject(_find_obj(doc, ref).InstanceGuid)
        grp.Colour = System.Drawing.Color.FromArgb(120, 255, 214, 150)
        doc.AddObject(grp, False, APPEND)
        return {"group": str(grp.InstanceGuid)}
    return on_ui(work)


def cmd_gh_free_spot(args):
    """A canvas position below everything that's already there."""
    def work():
        doc = _gh_doc()
        bottom = 0.0
        for obj in doc.Objects:
            try:
                b = obj.Attributes.Bounds
                bottom = max(bottom, float(b.Bottom))
            except Exception:  # noqa: BLE001
                pass
        return {"x": 80.0, "y": bottom + 80.0}
    return on_ui(work)


# --------------------------------------------------------------------------- #
# Kazi builds: remember what voice/MCP built, so it can be undone, baked or edited
# --------------------------------------------------------------------------- #

def _builds():
    return sc.sticky.setdefault(BUILDS_KEY, [])


def cmd_kazi_record_build(args):
    record = {k: args.get(k) for k in ("title", "group", "script", "components", "sliders", "toggles",
                                       "request", "recipe")}
    _builds().append(record)
    del _builds()[:-20]  # keep the last 20
    return {"recorded": len(_builds())}


def cmd_kazi_builds(args):
    return {"builds": list(_builds())}


def _pick_build(args):
    builds = _builds()
    if not builds:
        raise ValueError("Nothing built with kazi yet in this Rhino session.")
    ref = args.get("group")
    if ref:
        for b in builds:
            if b.get("group") == ref or b.get("title") == ref:
                return b
        raise ValueError("No kazi build '%s'" % ref)
    return builds[-1]


def cmd_kazi_undo_build(args):
    """Delete the components of the last (or a named) kazi build from the canvas."""
    def work():
        doc = _gh_doc()
        build = _pick_build(args)
        removed = 0
        for ref in list(build.get("components") or []) + [build.get("group")]:
            try:
                doc.RemoveObject(_find_obj(doc, ref), False)
                removed += 1
            except ValueError:
                pass
        doc.NewSolution(False)
        _builds().remove(build)
        Rhino.RhinoApp.WriteLine("[kazi] removed '%s' (%d components)" % (build.get("title"), removed))
        return {"removed": removed, "title": build.get("title")}
    return on_ui(work)


def cmd_kazi_bake(args):
    """Bake the script outputs of the last (or a named) build to layers kazi::<title>::<output>."""
    def work():
        gh = _gh()
        doc = _gh_doc()
        rdoc = Rhino.RhinoDoc.ActiveDoc
        build = _pick_build(args)
        script = _find_obj(doc, build.get("script"))
        undo = rdoc.BeginUndoRecord("kazi bake")
        baked = {}
        try:
            for p in script.Params.Output:
                if str(p.NickName) == "out":
                    continue
                path = "kazi::%s::%s" % (build.get("title"), p.NickName)
                idx = rdoc.Layers.FindByFullPath(path, -1)
                if idx < 0:
                    idx = rdoc.Layers.AddPath(path)
                attrs = Rhino.DocObjects.ObjectAttributes()
                attrs.LayerIndex = idx
                n = 0
                for goo in p.VolatileData.AllData(True):
                    geo = gh.Kernel.GH_Convert.ToGeometryBase(goo)
                    if geo is not None and rdoc.Objects.Add(geo, attrs) != System.Guid.Empty:
                        n += 1
                baked[str(p.NickName)] = n
        finally:
            rdoc.EndUndoRecord(undo)
        rdoc.Views.Redraw()
        Rhino.RhinoApp.WriteLine("[kazi] baked '%s': %s" % (build.get("title"), baked))
        return {"baked": baked, "title": build.get("title")}
    return on_ui(work)


def cmd_gh_set_slider(args):
    """Set a slider's value; widens the range if the value is outside it."""
    def work():
        doc = _gh_doc()
        slider = _find_obj(doc, args["component"])
        if not hasattr(slider, "SetSliderValue"):
            raise ValueError("%s is not a number slider" % slider.NickName)
        val = float(args["value"])
        s = slider.Slider
        if val < float(s.Minimum):
            s.Minimum = System.Decimal(val)
        if val > float(s.Maximum):
            s.Maximum = System.Decimal(val)
        slider.SetSliderValue(System.Decimal(val))
        slider.ExpireSolution(True)
        return {"nickname": str(slider.NickName), "value": float(slider.CurrentValue),
                "min": float(s.Minimum), "max": float(s.Maximum)}
    return on_ui(work)


def cmd_gh_toggle(args):
    """Read a Boolean Toggle, or set it when `value` is given."""
    def work():
        toggle = _find_obj(_gh_doc(), args["component"])
        if not hasattr(toggle, "Value") or not isinstance(toggle.Value, bool):
            raise ValueError("%s is not a boolean toggle" % toggle.NickName)
        if args.get("value") is not None:
            toggle.Value = bool(args["value"])
            toggle.ExpireSolution(True)
        return {"nickname": str(toggle.NickName), "value": bool(toggle.Value)}
    return on_ui(work)


def cmd_gh_get_slider(args):
    def work():
        slider = _find_obj(_gh_doc(), args["component"])
        s = slider.Slider
        return {"nickname": str(slider.NickName), "value": float(slider.CurrentValue),
                "min": float(s.Minimum), "max": float(s.Maximum),
                "integer": int(s.DecimalPlaces) == 0}
    return on_ui(work)


COMMANDS = {
    "ping": cmd_ping,
    "run_command": cmd_run_command,
    "list_rhino_commands": cmd_list_rhino_commands,
    "gh_create_script": cmd_gh_create_script,
    "gh_update_script": cmd_gh_update_script,
    "gh_read_script": cmd_gh_read_script,
    "gh_list": cmd_gh_list,
    "gh_add_component": cmd_gh_add_component,
    "gh_connect": cmd_gh_connect,
    "gh_disconnect": cmd_gh_disconnect,
    "gh_delete": cmd_gh_delete,
    "gh_solve": cmd_gh_solve,
    "get_selection": cmd_get_selection,
    "confirm": cmd_confirm,
    "rhino_message": cmd_rhino_message,
    "gh_add_slider": cmd_gh_add_slider,
    "gh_add_toggle": cmd_gh_add_toggle,
    "gh_add_geometry_input": cmd_gh_add_geometry_input,
    "gh_group": cmd_gh_group,
    "gh_free_spot": cmd_gh_free_spot,
    "gh_set_slider": cmd_gh_set_slider,
    "gh_get_slider": cmd_gh_get_slider,
    "gh_toggle": cmd_gh_toggle,
    "kazi_record_build": cmd_kazi_record_build,
    "kazi_builds": cmd_kazi_builds,
    "kazi_undo_build": cmd_kazi_undo_build,
    "kazi_bake": cmd_kazi_bake,
}


# --------------------------------------------------------------------------- #
# Extensions: extra commands from files next to this one
# --------------------------------------------------------------------------- #

EXTENSIONS = ("kazi_addons",)  # kazi_addons.py: components from installed Grasshopper plug-ins


def _load_extensions():
    import importlib.util
    import os
    import types
    loaded = []
    try:
        here = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        here = sc.sticky.get("kazi_bridge_dir") or ""
    for name in EXTENSIONS:
        path = os.path.join(here, name + ".py")
        if not os.path.isfile(path):
            continue
        try:
            spec = importlib.util.spec_from_file_location(name, path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.register(types.SimpleNamespace(**globals()))
            loaded.append("%s %s" % (name, getattr(mod, "VERSION", "")))
        except Exception as exc:  # noqa: BLE001  (an extension must never stop the bridge)
            print("[kazi] could not load %s: %s" % (name, exc))
    return loaded


LOADED_EXTENSIONS = _load_extensions()


# --------------------------------------------------------------------------- #
# TCP server
# --------------------------------------------------------------------------- #

class Bridge(object):
    def __init__(self, host=HOST, port=PORT):
        self.host, self.port = host, port
        self.running = False
        self.sock = None
        self.thread = None

    def start(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))
        self.sock.listen(5)
        self.sock.settimeout(1.0)
        self.running = True
        self.thread = threading.Thread(target=self._loop, name="rhino-ai-bridge")
        self.thread.daemon = True
        self.thread.start()

    def stop(self):
        self.running = False
        try:
            self.sock.close()
        except Exception:  # noqa: BLE001
            pass

    def _loop(self):
        while self.running:
            try:
                conn, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            t = threading.Thread(target=self._serve, args=(conn,))
            t.daemon = True
            t.start()

    def _serve(self, conn):
        conn.settimeout(None)
        buf = b""
        try:
            while self.running:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if line.strip():
                        conn.sendall((json.dumps(self._handle(line)) + "\n").encode("utf-8"))
        except Exception:  # noqa: BLE001
            pass
        finally:
            conn.close()

    def _handle(self, line):
        req_id = None
        try:
            req = json.loads(line.decode("utf-8"))
            req_id = req.get("id")
            fn = COMMANDS.get(req.get("cmd"))
            if fn is None:
                raise ValueError("Unknown cmd '%s'. Known: %s" % (req.get("cmd"), ", ".join(sorted(COMMANDS))))
            return {"id": req_id, "ok": True, "result": fn(req.get("args") or {})}
        except Exception as exc:  # noqa: BLE001
            return {"id": req_id, "ok": False, "error": str(exc)}


def main():
    old = sc.sticky.get(STICKY_KEY)
    if old is not None:
        old.stop()
        old.thread.join(2.0)
    bridge = Bridge(HOST, PORT)
    bridge.start()
    sc.sticky[STICKY_KEY] = bridge
    sc.sticky[COMMANDS_KEY] = COMMANDS
    print("rhino-ai-mods bridge %s listening on %s:%d" % (VERSION, HOST, bridge.sock.getsockname()[1]))


if __name__ == "__main__":
    main()
