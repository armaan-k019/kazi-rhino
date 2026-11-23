"""The free Grasshopper add-ons kazi knows about: how they are spoken, found and installed."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Addon:
    id: str
    title: str
    what_for: str
    spoken: str                       # regex: the add-on's name as people (and speech-to-text) say it
    categories: tuple[str, ...]       # Grasshopper ribbon tab names its components live under
    libraries: tuple[str, ...] = ()   # names of its .gha libraries (as Grasshopper reports them)
    probe: tuple[str, ...] = ()       # a component that proves the add-on is installed
    probe_scoped: bool = True         # False: look for the probe in any tab (Hops sits in Params)
    install: str = "package_manager"  # package_manager | installer | built_in
    package: str | None = None        # name to search for in Rhino's PackageManager
    url: str = ""
    licence: str = "free"
    notes: tuple[str, ...] = field(default_factory=tuple)
    topics: str = ""                  # regex: things only this add-on does ("sun path", "tween")

    def scope(self) -> dict:
        """Arguments that tell the bridge which plug-in a component must come from."""
        return {"categories": list(self.categories), "libraries": list(self.libraries)}

    def install_hint(self) -> str:
        if self.install == "built_in":
            return f"{self.title} ships with Rhino 8. If it is missing, repair the Rhino install."
        if self.install == "package_manager":
            return (f"Install {self.title}: type PackageManager in Rhino, search for "
                    f"\"{self.package}\", click Install, then restart Rhino. If it is not "
                    f"listed there, download it from {self.url}")
        return f"Install {self.title} with its installer from {self.url}, then restart Rhino."


ADDONS: dict[str, Addon] = {a.id: a for a in (
    Addon("lunchbox", "LunchBox", "panelling surfaces, structures (diagrid, space truss), "
          "Excel and bake utilities",
          r"lunch ?box", ("LunchBox",), ("LunchBox",), ("Quad Panels",),
          package="LunchBox", url="https://www.food4rhino.com/en/app/lunchbox"),
    Addon("ladybug", "Ladybug Tools", "sun path, sun hours, radiation, wind rose and the "
          "Honeybee / Dragonfly energy and daylight models",
          r"lady ?bug|honey ?bee|dragon ?fly",
          ("Ladybug", "Honeybee", "HB-Radiance", "HB-Energy", "Dragonfly"), (), ("LB SunPath",),
          install="installer", url="https://www.food4rhino.com/en/app/ladybug-tools",
          topics=r"sun ?path|sun ?(?:light )?hours|hours of sun|(?:solar|incident) radiation|"
                 r"radiation (?:study|analysis|map)|wind ?rose|\bepw\b|weather file",
          licence="free, open source (AGPL)",
          notes=("Also needs the free Radiance and OpenStudio programs for Honeybee daylight and "
                 "energy runs; Ladybug sun and radiation studies work without them.",)),
    Addon("kangaroo2", "Kangaroo 2", "physics: form-finding, tensile and hanging shapes, "
          "relaxation, planarisation",
          r"kanga ?roo",
          ("Kangaroo2",), ("Kangaroo2Components", "Kangaroo"), ("Solver",), install="built_in",
          url="https://www.food4rhino.com/en/app/kangaroo-physics",
          topics=r"form[- ]?find|tensile|membrane|catenary|hanging (?:chain|cloth|model|shell)|"
                 r"relax (?:the |this |my |a )?(?:mesh|surface|facade|shape)"),
    Addon("weaverbird", "Weaverbird", "mesh subdivision, frames, windows and thickening",
          r"weaver ?bird",
          ("Weaverbird", "Wb"), ("Weaverbird",), ("Catmull-Clark Subdivision",),
          package="Weaverbird", url="https://www.giuliopiacentino.com/weaverbird/",
          topics=r"catmull|loop subdivi|subdivide (?:the |this |my )?mesh|picture ?frame|"
                 r"mesh window|thicken (?:the |this |my )?mesh|stellat"),
    Addon("pufferfish", "Pufferfish", "tweens, blends, morphs and offsets between shapes",
          r"puffer ?fish", ("Pufferfish",), ("Pufferfish",), ("Tween Through Curves",),
          package="Pufferfish", url="https://www.food4rhino.com/en/app/pufferfish",
          topics=r"\btween"),
    Addon("elefront", "Elefront", "baking with layers, names and user attributes; referencing "
          "Rhino objects by layer or name",
          r"ele ?front|elephant|l front|elle front", ("Elefront",), ("Elefront",), ("Bake Objects",),
          package="Elefront", url="https://www.food4rhino.com/en/app/elefront"),
    Addon("human", "Human", "reading and changing Rhino layers, attributes, views and display "
          "from Grasshopper",
          r"\bhuman (?:plug ?in|add ?on|components?|tools?)\b|\b(?:with|using|use|in|from) human\b",
          ("Human",), ("Human",), ("Layer Table",), package="Human",
          url="https://www.food4rhino.com/en/app/human"),
    Addon("wallacei", "Wallacei", "evolutionary multi-objective optimisation",
          r"wallace ?i\b|wallacei|wallace e\b|wallacy",
          ("Wallacei",), ("Wallacei",), ("Wallacei X",), package="Wallacei",
          url="https://www.wallacei.com/",
          topics=r"evolutionary|multi[- ]?objective|optimi[sz]e (?:this|that|it|the|my)"),
    Addon("hops", "Hops", "running another Grasshopper file, or a Python function, as one "
          "component (Rhino.Compute)",
          r"\bhops\b|rhino ?compute", ("Params",), ("Hops",), ("Hops",), probe_scoped=False,
          package="Hops", url="https://developer.rhino3d.com/guides/compute/hops-component/",
          notes=("Windows only.",)),
    Addon("speckle", "Speckle", "sending and receiving models between Rhino, Revit, Blender and "
          "the web",
          r"speckle|speckel|speckled", ("Speckle",), ("Speckle",), ("Publish",),
          install="installer", url="https://app.speckle.systems/connectors",
          licence="free plan, open source connector",
          notes=("Needs a free Speckle account. Publish and Load run when you click the button "
                 "on the component.",)),
)}


def mentioned(text: str, strict: bool = False) -> list[str]:
    """Add-on ids a request refers to, in the order they are mentioned.

    strict=True: only when the add-on is named ("with lunchbox"). Otherwise also when the
    request is about something only that add-on does ("sun path", "tween these curves").
    """
    low = re.sub(r"\s+", " ", (text or "").lower())
    hits = []
    for addon in ADDONS.values():
        m = re.search(addon.spoken, low)
        if m:
            hits.append((0, m.start(), addon.id))      # a named add-on beats an implied one
        elif not strict and addon.topics:
            m = re.search(addon.topics, low)
            if m:
                hits.append((1, m.start(), addon.id))
    return [aid for _rank, _pos, aid in sorted(hits)]
