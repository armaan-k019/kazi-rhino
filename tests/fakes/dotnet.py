"""Fake System / Rhino / Grasshopper / scriptcontext modules for running bridge/rhino_ai_bridge.py
outside Rhino. Objects behave like the real API surface the bridge uses (names checked against
RhinoCommon 8 by tools/check_rhino_api.py), with just enough behaviour to test the logic.
"""

from __future__ import annotations

import itertools
import queue
import sys
import threading
import types
import uuid

# --------------------------------------------------------------------------- #
# System
# --------------------------------------------------------------------------- #

class _Event:
    def __init__(self, state):
        self._e = threading.Event()
        if state:
            self._e.set()

    def Set(self):
        self._e.set()

    def WaitOne(self, ms):
        return self._e.wait(ms / 1000.0)


class _Guid:
    def __init__(self, s):
        self.value = str(uuid.UUID(str(s)))

    def __str__(self):
        return self.value

    def __eq__(self, other):
        return str(self) == str(other)

    def __hash__(self):
        return hash(self.value)


class _PointF:
    def __init__(self, x, y):
        self.X, self.Y = x, y


class _BindingFlags:
    Public, NonPublic, Instance, DeclaredOnly = 1, 2, 4, 8


def make_system():
    system = types.ModuleType("System")
    system.Action = lambda fn: fn
    system.Threading = types.SimpleNamespace(ManualResetEvent=_Event)
    system.Guid = _Guid
    _Guid.Empty = _Guid(uuid.UUID(int=0))
    system.Decimal = float
    system.Drawing = types.SimpleNamespace(PointF=_PointF,
                                           Color=types.SimpleNamespace(FromArgb=lambda *a: a))
    system.Reflection = types.SimpleNamespace(BindingFlags=_BindingFlags)
    system.String = str
    return system


# --------------------------------------------------------------------------- #
# Rhino
# --------------------------------------------------------------------------- #

class FakeRhinoApp:
    """InvokeOnUiThread runs actions on a single dedicated 'UI' thread, like Rhino."""

    Version = "8.36.26296.17001"

    def __init__(self):
        self.keystrokes, self.scripts, self.lines = [], [], []
        self.in_command = False
        self.dialog_answer = True
        self.dialogs = []
        self.ui_thread_ids = set()
        self._q = queue.Queue()
        threading.Thread(target=self._ui_loop, daemon=True).start()

    def _ui_loop(self):
        self.ui_thread_ids.add(threading.get_ident())
        while True:
            self._q.get()()

    @property
    def IsOnMainThread(self):
        return threading.get_ident() in self.ui_thread_ids

    def run_on_ui(self, fn):
        """Run fn on the UI thread and wait (how a script started from Rhino's command bar runs)."""
        box, done = {}, threading.Event()

        def go():
            try:
                box["r"] = fn()
            except Exception as exc:  # noqa: BLE001
                box["e"] = exc
            done.set()
        self._q.put(go)
        assert done.wait(5)
        if "e" in box:
            raise box["e"]
        return box.get("r")

    def InvokeOnUiThread(self, action):
        self._q.put(action)

    def SendKeystrokes(self, text, enter):
        assert threading.get_ident() in self.ui_thread_ids, "must be called on the UI thread"
        self.keystrokes.append((text, enter))

    def RunScript(self, macro, echo):
        self.scripts.append(macro)
        return True

    def WriteLine(self, text):
        self.lines.append(text)


class _RhinoObject:
    def __init__(self, geometry, name="", layer=0):
        self.Id = _Guid(uuid.uuid4())
        self.Geometry = geometry
        self.Attributes = types.SimpleNamespace(LayerIndex=layer, Name=name)


class _Geometry:
    def __init__(self, kind):
        self.kind = kind

    def GetType(self):
        return types.SimpleNamespace(Name=self.kind, FullName="Rhino.Geometry." + self.kind)


class _Layer:
    def __init__(self, path):
        self.FullPath = path


class _Layers(list):
    def FindByFullPath(self, path, not_found):
        for i, layer in enumerate(self):
            if layer.FullPath == path:
                return i
        return not_found

    def AddPath(self, path):
        parts = path.split("::")
        for k in range(1, len(parts) + 1):
            sub = "::".join(parts[:k])
            if self.FindByFullPath(sub, -1) < 0:
                self.append(_Layer(sub))
        return self.FindByFullPath(path, -1)


class _Aliases:
    def __init__(self):
        self.items = {}

    def IsAlias(self, name):
        return name in self.items

    def Add(self, name, macro):
        assert name not in self.items
        self.items[name] = macro
        return True

    def SetMacro(self, name, macro):
        self.items[name] = macro
        return True


def make_rhino(app: FakeRhinoApp, commands):
    selected = []
    added = []
    layers = _Layers([_Layer("Default"), _Layer("Facade")])

    def add_object(geo, attrs):
        added.append((geo, attrs.LayerIndex))
        return _Guid(uuid.uuid4())

    undo = []
    doc = types.SimpleNamespace(
        Name="facade_study.3dm",
        ModelAbsoluteTolerance=0.001,
        Objects=types.SimpleNamespace(GetSelectedObjects=lambda a, b: list(selected), Add=add_object),
        Layers=layers,
        BeginUndoRecord=lambda name: undo.append(("begin", name)) or 7,
        EndUndoRecord=lambda sn: undo.append(("end", sn)) or True,
        Views=types.SimpleNamespace(Redraw=lambda: None),
    )
    rhino = types.ModuleType("Rhino")
    rhino.RhinoApp = app
    rhino.RhinoDoc = types.SimpleNamespace(ActiveDoc=doc)
    rhino.Commands = types.SimpleNamespace(Command=types.SimpleNamespace(
        GetCommandNames=lambda english, loaded: list(commands),
        InCommand=lambda: app.in_command))

    def show_message(message, title, buttons, icon):
        app.dialogs.append((title, message))
        return "Yes" if app.dialog_answer else "No"

    rhino.UI = types.SimpleNamespace(
        Dialogs=types.SimpleNamespace(ShowMessage=show_message),
        ShowMessageButton=types.SimpleNamespace(YesNo="YesNo"),
        ShowMessageIcon=types.SimpleNamespace(Question="Question"),
        ShowMessageResult=types.SimpleNamespace(Yes="Yes", No="No"))
    rhino.selected = selected
    rhino.added = added
    rhino.undo = undo
    rhino.DocObjects = types.SimpleNamespace(ObjectAttributes=lambda: types.SimpleNamespace(LayerIndex=0))
    rhino.ApplicationSettings = types.SimpleNamespace(CommandAliasList=_Aliases())
    rhino.make_object = lambda kind, name="", layer=1: _RhinoObject(_Geometry(kind), name, layer)
    return rhino


# --------------------------------------------------------------------------- #
# Grasshopper
# --------------------------------------------------------------------------- #

_ids = itertools.count(1)


def _new_guid():
    return _Guid(uuid.UUID(int=next(_ids)))


class _Type:
    def __init__(self, full):
        self.FullName, self.Name = full, full.rsplit(".", 1)[-1]
        self.BaseType = None

    def GetProperty(self, name, flags):
        return None


class _Attributes:
    def __init__(self, owner):
        self.Pivot = _PointF(0.0, 0.0)
        self.Bounds = types.SimpleNamespace(Bottom=0.0)
        self.DocObject = owner
        self.GetTopLevel = self


class _Structure(list):
    @property
    def DataCount(self):
        return len(self)

    def AllData(self, skip_nulls):
        return list(self)

    def Append(self, item):
        self.append(item)


class DocObject:
    TYPE = "Grasshopper.Kernel.GH_DocumentObject"

    def __init__(self, name="", nickname=""):
        self.Name, self.NickName = name, nickname or name
        self.InstanceGuid = _new_guid()
        self.Attributes = None
        self.expired = 0
        self.messages = []

    def GetType(self):
        return _Type(self.TYPE)

    def CreateAttributes(self):
        self.Attributes = _Attributes(self)

    def ExpireSolution(self, recompute):
        self.expired += 1

    def ClearData(self):
        pass

    def RuntimeMessages(self, level):
        return [t for lv, t in self.messages if lv == level]


class Param(DocObject):
    TYPE = "Grasshopper.Kernel.Parameters.Param_GenericObject"

    def __init__(self, name="x", access="item"):
        super().__init__(name, name)
        self.Access, self.Optional, self.Description = access, False, ""
        self.Sources = []
        self.VolatileData = _Structure()
        self.PersistentData = _Structure()
        self.CreateAttributes()

    def AddSource(self, src):
        self.Sources.append(src)

    def RemoveAllSources(self):
        self.Sources.clear()


class ParamGeometry(Param):
    TYPE = "Grasshopper.Kernel.Parameters.Param_Geometry"

    def __init__(self):
        super().__init__("Geometry")


class _ParamList(list):
    def IndexOf(self, p):
        return self.index(p)


class _ParamServer:
    def __init__(self, owner):
        self.owner = owner
        self.Input, self.Output = _ParamList(), _ParamList()
        self.changed = 0

    def RegisterInputParam(self, p, index):
        self.Input.insert(index, p)

    def RegisterOutputParam(self, p, index):
        self.Output.insert(index, p)

    def UnregisterInputParameter(self, p, isolate):
        self.Input.remove(p)

    def UnregisterOutputParameter(self, p, isolate):
        self.Output.remove(p)

    def OnParametersChanged(self):
        self.changed += 1


class Component(DocObject):
    TYPE = "Grasshopper.Kernel.Components.GenericComponent"

    def __init__(self, name, inputs=("A",), outputs=("R",)):
        super().__init__(name, name)
        self.Params = _ParamServer(self)
        for i, n in enumerate(inputs):
            self.Params.RegisterInputParam(Param(n), i)
        for i, n in enumerate(outputs):
            self.Params.RegisterOutputParam(Param(n), i)


class ScriptComponent(Component):
    """Rhino 8 'Python 3 Script': x, y -> (out,) a; variable params; SetSource."""

    TYPE = "RhinoCodePluginGH.Components.Python3Component"

    def __init__(self, with_out=True):
        super().__init__("Python 3 Script", ("x", "y"), (("out", "a") if with_out else ("a",)))
        self.source = "# new script"
        self.maintenance = 0

    def SetSource(self, code):
        self.source = code

    def TryGetSource(self):
        return True, self.source

    def CanInsertParameter(self, side, index):
        return True

    def CreateParameter(self, side, index):
        return Param("p%d" % index)

    def VariableParameterMaintenance(self):
        self.maintenance += 1


class Slider(Param):
    TYPE = "Grasshopper.Kernel.Special.GH_NumberSlider"

    def __init__(self):
        super().__init__("Number Slider")
        self.Attributes = None
        self.Slider = types.SimpleNamespace(Type=None, DecimalPlaces=2, Minimum=0.0, Maximum=1.0)
        self.value = None

    @property
    def CurrentValue(self):
        return self.value
        self.Sources = []

    def SetSliderValue(self, v):
        assert self.Slider.Minimum <= v <= self.Slider.Maximum, "value outside slider range"
        self.value = v
        return True


class Toggle(Param):
    TYPE = "Grasshopper.Kernel.Special.GH_BooleanToggle"

    def __init__(self):
        super().__init__("Boolean Toggle")
        self.Attributes = None
        self.Value = False
        self.Sources = []


class Group(DocObject):
    TYPE = "Grasshopper.Kernel.Special.GH_Group"

    def __init__(self):
        super().__init__("Group", "Group")
        self.members = []
        self.Colour = None

    def AddObject(self, guid):
        self.members.append(guid)


class GHDocument:
    def __init__(self):
        self.Objects = []
        self.solutions = 0

    def AddObject(self, obj, update, index):
        assert index == 2147483647
        self.Objects.append(obj)
        return True

    def FindObject(self, guid, top_level):
        return next((o for o in self.Objects if o.InstanceGuid == guid), None)

    def RemoveObject(self, obj, update):
        self.Objects.remove(obj)

    def NewSolution(self, expire_all):
        self.solutions += 1


class _Proxy:
    def __init__(self, name, nickname, factory, obsolete=False):
        self.Desc = types.SimpleNamespace(Name=name, NickName=nickname)
        self.Obsolete = obsolete
        self.CreateInstance = factory


class _Goo:
    def __init__(self, geometry):
        self.geometry = geometry
        self.ReferenceID = None
        self.loaded = False

    def LoadGeometry(self, doc):
        self.loaded = True
        return True


def make_grasshopper(open_canvas=True, script_with_out=True):
    gh = types.ModuleType("Grasshopper")
    doc = GHDocument()
    canvas = types.SimpleNamespace(Document=doc, refreshed=0)
    canvas.Refresh = lambda: setattr(canvas, "refreshed", canvas.refreshed + 1)
    proxies = [
        _Proxy("Python 3 Script", "Py3", lambda: ScriptComponent(script_with_out)),
        _Proxy("C# Script", "C#", lambda: ScriptComponent(script_with_out)),
        _Proxy("Loft", "Loft", lambda: Component("Loft", ("Curves", "Options"), ("Loft",))),
        _Proxy("Divide Curve", "Divide", lambda: Component("Divide Curve", ("Curve", "Count", "Kinks"),
                                                            ("Points", "Tangents", "Parameters"))),
        _Proxy("Old Loft", "Loft", lambda: Component("Old"), obsolete=True),
    ]
    gh.Instances = types.SimpleNamespace(
        ActiveCanvas=canvas if open_canvas else None,
        ComponentServer=types.SimpleNamespace(ObjectProxies=proxies),
        DocumentServer=types.SimpleNamespace(AddDocument=lambda d: None))
    levels = types.SimpleNamespace(Error="Error", Warning="Warning", Remark="Remark")
    gh.Kernel = types.SimpleNamespace(
        GH_Document=GHDocument,
        GH_ParameterSide=types.SimpleNamespace(Input="Input", Output="Output"),
        GH_ParamAccess=types.SimpleNamespace(item="item", list="list", tree="tree"),
        GH_RuntimeMessageLevel=levels,
        IGH_VariableParameterComponent=lambda obj: obj,
        GH_Convert=types.SimpleNamespace(ToGeometricGoo=_Goo, ToGeometryBase=lambda goo: goo),
        Special=types.SimpleNamespace(GH_NumberSlider=Slider, GH_BooleanToggle=Toggle, GH_Group=Group),
        Parameters=types.SimpleNamespace(Param_Geometry=ParamGeometry))
    gh.GUI = types.SimpleNamespace(Base=types.SimpleNamespace(
        GH_SliderAccuracy=types.SimpleNamespace(Integer="Integer", Float="Float")))
    gh.doc = doc
    gh.canvas = canvas
    return gh


def install(commands=("Box", "SelPrev", "Loft"), **gh_kwargs):
    """Install fakes into sys.modules. Returns a namespace with handles for assertions."""
    app = FakeRhinoApp()
    system = make_system()
    rhino = make_rhino(app, commands)
    gh = make_grasshopper(**gh_kwargs)
    sc = types.ModuleType("scriptcontext")
    sc.sticky = {}
    sys.modules.update({"System": system, "Rhino": rhino, "Grasshopper": gh, "scriptcontext": sc})
    return types.SimpleNamespace(app=app, rhino=rhino, gh=gh, sc=sc)


def uninstall():
    for name in ("System", "Rhino", "Grasshopper", "scriptcontext"):
        sys.modules.pop(name, None)
