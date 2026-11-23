"""Fake plug-in components for the bridge simulator, generated from the add-on catalogs.

extend(env) adds to the fake Grasshopper made by fakes.dotnet: one component proxy per
catalogued component (with its tab, library and typed inputs / outputs), the list of loaded
libraries, panels, data-mapping and the GH_Number / GH_Integer / ... value types.
"""

from __future__ import annotations

import types
import uuid

from fakes import dotnet
from rhino_ai_mods.addons import catalog
from rhino_ai_mods.addons.registry import ADDONS

dotnet._Structure.Clear = lambda self: self.clear()  # GH_Structure.Clear, used by gh_set_input

_PARAM_TYPES = {"integer": "Param_Integer", "int": "Param_Integer", "number": "Param_Number",
                "double": "Param_Number", "boolean": "Param_Boolean", "bool": "Param_Boolean",
                "text": "Param_String", "string": "Param_String"}

# Tab each add-on's components appear under in Grasshopper
TABS = {"lunchbox": "LunchBox", "kangaroo2": "Kangaroo2", "weaverbird": "Weaverbird",
        "pufferfish": "Pufferfish", "elefront": "Elefront", "human": "Human",
        "wallacei": "Wallacei", "hops": "Params", "speckle": "Speckle", "ladybug": "Ladybug"}
LIBRARIES = {"lunchbox": "LunchBox", "kangaroo2": "Kangaroo2Components", "weaverbird": "Weaverbird",
             "pufferfish": "Pufferfish", "elefront": "Elefront", "human": "Human",
             "wallacei": "Wallacei", "hops": "Hops", "speckle": "Speckle.Connectors.Grasshopper8"}


class TypedParam(dotnet.Param):
    def __init__(self, name, nickname, kind="", persistent=True):
        super().__init__(name)
        self.NickName = nickname or name
        self.TypeName = kind or "Generic Data"
        self.TYPE = "Grasshopper.Kernel.Parameters." + _PARAM_TYPES.get(str(kind).lower(), "Param_GenericObject")
        self.DataMapping = "None"
        if not persistent:
            del self.PersistentData   # script-component inputs hold no values of their own


class PluginComponent(dotnet.Component):
    def __init__(self, comp, persistent=True):
        dotnet.DocObject.__init__(self, comp.name, comp.nickname or comp.name)
        self.Params = dotnet._ParamServer(self)
        ins = comp.inputs if comp.inputs else (("in0", "in0", ""), ("in1", "in1", ""),
                                               ("in2", "in2", ""), ("in3", "in3", ""))
        outs = comp.outputs if comp.outputs else (("out0", "out0", ""),)
        for i, (n, k, t) in enumerate(ins):
            self.Params.RegisterInputParam(TypedParam(n, k, t, persistent), i)
        for i, (n, k, t) in enumerate(outs):
            self.Params.RegisterOutputParam(TypedParam(n, k, t), i)
        if comp.name == "Hops":
            self.RemoteDefinitionLocation = ""


class Panel(dotnet.Param):
    TYPE = "Grasshopper.Kernel.Special.GH_Panel"

    def __init__(self):
        super().__init__("Panel")
        self.Attributes = None
        self.UserText = ""


class _Value:
    def __init__(self, value):
        self.Value = value

    def __repr__(self):
        return f"{type(self).__name__}({self.Value!r})"


def _value_type(name, cast):
    return type(name, (_Value,), {"__init__": lambda self, v: _Value.__init__(self, cast(v))})


def _library(name, core=False):
    return types.SimpleNamespace(Name=name, Id=dotnet._Guid(uuid.uuid5(uuid.NAMESPACE_DNS, name)),
                                 Version="1.0", AuthorName="someone", Location="C:\\plugins\\" + name + ".gha",
                                 IsCoreLibrary=core)


def _proxy(name, nickname, factory, category, subcategory="", description="", library=None,
           obsolete=False, kind="CompiledObject"):
    p = dotnet._Proxy(name, nickname, factory, obsolete)
    p.Desc.Category, p.Desc.SubCategory, p.Desc.Description = category, subcategory, description
    p.Guid = dotnet._Guid(uuid.uuid5(uuid.NAMESPACE_DNS, category + "/" + subcategory + "/" + name))
    p.LibraryGuid = library.Id if library else dotnet._Guid.Empty
    p.Kind = kind
    return p


def extend(env, addons=None, weaverbird_prefix=True):
    """Install the add-ons (default: all ten) into the fake Grasshopper. Returns env."""
    gh = env.gh
    cat = catalog.load()
    addons = list(ADDONS) if addons is None else list(addons)
    core = _library("Grasshopper", core=True)
    libs = [core]
    proxies = gh.Instances.ComponentServer.ObjectProxies
    for p in proxies:   # the built-in fakes: give them a tab and library like real ones
        if not hasattr(p.Desc, "Category"):
            p.Desc.Category, p.Desc.SubCategory, p.Desc.Description = "Maths", "Script", ""
            p.Guid = dotnet._Guid(uuid.uuid5(uuid.NAMESPACE_DNS, "core/" + p.Desc.Name + str(p.Obsolete)))
            p.LibraryGuid, p.Kind = core.Id, "CompiledObject"
    proxies.append(_proxy("Range", "Range", lambda: dotnet.Component("Range", ("Domain", "Steps"), ("Range",)),
                          "Sets", "Sequence", "Create a range of numbers.", core))
    # Same names as plug-in components, but in Grasshopper's own tabs: must not be picked
    proxies.append(_proxy("Offset Surface", "Offset", lambda: dotnet.Component("Offset Surface", ("S", "D"), ("S",)),
                          "Surface", "Util", "", core))
    proxies.append(_proxy("Mesh Edges", "MEdges", lambda: dotnet.Component("Mesh Edges", ("M",), ("E1",)),
                          "Mesh", "Analysis", "", core))
    for aid in addons:
        lib = _library(LIBRARIES[aid]) if aid in LIBRARIES else None
        if lib:
            libs.append(lib)
        for comp in cat.of(aid):
            tab, panel = TABS[aid], comp.panel
            if aid == "ladybug" and " / " in panel:
                tab, panel = panel.split(" / ", 1)
            if aid == "hops":
                panel = "Util"
            name = comp.name
            if aid == "weaverbird" and weaverbird_prefix:
                name = "Weaverbird's " + name
            persistent = aid != "ladybug"   # Ladybug components are script components
            def make(c=comp, per=persistent, tab=tab):
                obj = PluginComponent(c, per)
                obj.tab = tab
                return obj
            proxies.append(_proxy(name, comp.nickname or name, make,
                                  tab, panel, comp.description, lib,
                                  kind="UserObject" if aid == "ladybug" else "CompiledObject"))
    gh.Instances.ComponentServer.Libraries = libs
    gh.Kernel.Special.GH_Panel = Panel
    gh.Kernel.GH_DataMapping = types.SimpleNamespace(Flatten="Flatten", Graft="Graft")
    setattr(gh.Kernel.GH_DataMapping, "None", "None")
    gh.Kernel.Types = types.SimpleNamespace(
        GH_Number=_value_type("GH_Number", float), GH_Integer=_value_type("GH_Integer", int),
        GH_Boolean=_value_type("GH_Boolean", bool), GH_String=_value_type("GH_String", str))
    return env
