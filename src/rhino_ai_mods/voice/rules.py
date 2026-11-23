"""Fast, offline rules that turn short spoken phrases into Rhino macros.

Rules run before any model, so common commands ("undo", "zoom extents", "boolean union",
"circle 0,0,0 5") are instant and never misinterpreted.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass
from pathlib import Path

# Spoken phrase -> macro. Keys are normalized (lowercase, no punctuation).
ALIASES: dict[str, str] = {
    "undo": "_Undo",
    "undo that": "_Undo",
    "redo": "_Redo",
    "repeat": "",
    "again": "",
    "repeat last command": "",
    "cancel": "!",
    "escape": "!",
    "zoom extents": "_Zoom _All _Extents",
    "zoom all": "_Zoom _All _Extents",
    "zoom out": "_Zoom _All _Extents",
    "zoom selected": "_Zoom _Selected",
    "zoom to selection": "_Zoom _Selected",
    "select all": "_SelAll",
    "select none": "_SelNone",
    "deselect": "_SelNone",
    "deselect all": "_SelNone",
    "select last": "_SelLast",
    "select curves": "_SelCrv",
    "select surfaces": "_SelSrf",
    "select polysurfaces": "_SelPolysrf",
    "invert selection": "_Invert",
    "hide": "_Hide",
    "hide that": "_Hide",
    "show all": "_Show",
    "show": "_Show",
    "isolate": "_Isolate",
    "unisolate": "_Unisolate",
    "lock": "_Lock",
    "unlock all": "_Unlock",
    "save": "_Save",
    "top view": "_SetView _World _Top",
    "bottom view": "_SetView _World _Bottom",
    "front view": "_SetView _World _Front",
    "back view": "_SetView _World _Back",
    "right view": "_SetView _World _Right",
    "left view": "_SetView _World _Left",
    "perspective view": "_SetView _World _Perspective",
    "perspective": "_SetView _World _Perspective",
    "maximize viewport": "_MaxViewport",
    "wireframe": "_-SetDisplayMode _Mode=Wireframe",
    "shaded": "_-SetDisplayMode _Mode=Shaded",
    "rendered": "_-SetDisplayMode _Mode=Rendered",
    "ghosted": "_-SetDisplayMode _Mode=Ghosted",
    "x ray": "_-SetDisplayMode _Mode=XRay",
    "arctic": "_-SetDisplayMode _Mode=Arctic",
    "technical": "_-SetDisplayMode _Mode=Technical",
    "pen": "_-SetDisplayMode _Mode=Pen",
    "open grasshopper": "_Grasshopper",
    "grasshopper": "_Grasshopper",
    "gumball": "_Gumball _Toggle",
    "toggle gumball": "_Gumball _Toggle",
    "osnap": "_Osnap",
    "ortho": "_Ortho",
    "grid snap": "_Snap",
    "planar": "_Planar",
    "join": "_Join",
    "explode": "_Explode",
    "group": "_Group",
    "ungroup": "_Ungroup",
    "delete": "_Delete",
    "delete that": "_Delete",
}

# Commands that are never auto-confirmed: they are typed into the command line and wait
# for the user to press Enter.
CONFIRM_COMMANDS = {
    "exit", "close", "new", "open", "purge", "delete", "import", "insert", "revert",
    "saveas", "closeall", "deleteall",
}

# Used when the bridge can't supply Rhino's live command list.
FALLBACK_COMMANDS = """
Arc Array ArrayCrv ArrayPolar Block BooleanDifference BooleanIntersection BooleanSplit
BooleanUnion Box Cap Chamfer ChangeLayer Circle Cone Contour Copy Curve CurveBoolean
Cylinder Delete Dim Distance Divide Dot Ellipse Explode Extend ExtrudeCrv ExtrudeSrf
Fillet FilletEdge Flow Group Hatch Hide Intersect Join Layer Line Lines Loft Make2D
Mirror Move NetworkSrf Offset OffsetSrf Orient Patch Pipe PlanarSrf Point Points
Polygon Polyline Project Rebuild Rectangle Revolve Rotate Rotate3D Scale Scale1D
Scale2D Section SelAll SelNone Show Sphere Split Sweep1 Sweep2 Text Torus Trim Tube
Ungroup Unroll Grasshopper Zoom SetView Undo Redo Save Export Import Render
ProjectToCPlane SetPt Smash Squish Area Volume Length BoundingBox Cplane Gumball
Osnap Ortho Planar Snap MaxViewport Isolate Unisolate Lock Unlock Invert Properties
Layout Make2D Clippingplane NamedView Named Purge Exit Close New Open SelPrev SelLast
SelCrv SelSrf SelPolysrf SelPt SelLayer SelColor SelDup SelBadObjects SelGroup SelClosedCrv
SelOpenCrv SelMesh SelBlockInstance SelText SelDim DupEdge DupBorder ExtractSrf MatchSrf
PlanarSrf NetworkSrf ExtrudeCrv OffsetSrf Sweep1 Sweep2 CurvatureAnalysis ZebraAnalysis
PointsOn PointsOff Rebuild Fair ShowEdges Check What Analyze Dir Flip Shell ExtractIsocurve
""".split()

_NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100,
}

# Words speech-to-text commonly gets wrong for Rhino vocabulary.
MISHEARINGS = {
    "bullion": "boolean", "boolian": "boolean", "fillit": "fillet", "filet": "fillet",
    "lofted": "loft", "nerbs": "nurbs", "rhinos": "rhino", "grass hopper": "grasshopper",
    "c plane": "cplane", "sub d": "subd", "poly line": "polyline", "poly surface": "polysurface",
}
_TRAILING = re.compile(r"(?:\s+(?:please|thanks|thank you|now))+$")
_FILLERS = re.compile(r"^(?:(?:please|hey rhino|ok rhino|okay rhino|rhino|now|and|then|just)\s+)+")
_EXPLICIT = re.compile(r"^(?:run|command|type)\s+(.+)$")
_ARG_TOKEN = re.compile(r"^[-+]?\d*\.?\d+(?:,[-+]?\d*\.?\d+){0,2}$|^_?[A-Za-z]+=\S+$")


@dataclass
class Match:
    macro: str
    source: str          # "alias" | "command" | "llm" | "raw"
    command: str | None  # canonical command name, if known
    needs_confirm: bool = False


def words_to_numbers(text: str) -> str:
    """'two point five' -> '2.5', 'twenty five' -> '25', 'minus three' -> '-3'."""
    tokens = text.split()
    out: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in _NUMBER_WORDS:
            value = _NUMBER_WORDS[tok]
            j = i + 1
            if value >= 20 and j < len(tokens) and tokens[j] in _NUMBER_WORDS and _NUMBER_WORDS[tokens[j]] < 10:
                value += _NUMBER_WORDS[tokens[j]]
                j += 1
            out.append(str(value))
            i = j
            continue
        out.append(tok)
        i += 1
    text = " ".join(out)
    text = re.sub(r"(\d+) point (\d+)", r"\1.\2", text)
    text = re.sub(r"\b(?:minus|negative) (\d)", r"-\1", text)
    return text


def normalize(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[\"“”!?]", "", text)
    text = text.rstrip(".;: ")
    text = words_to_numbers(text)
    # "0 comma 0 comma 0" / "0, 0, 0" -> "0,0,0"
    text = re.sub(r"\s*\bcomma\b\s*", ",", text)
    text = re.sub(r"(?<=\d),\s+(?=[-\d])", ",", text)
    text = re.sub(r",(?![-\d])", " ", text)  # commas that aren't coordinates
    text = re.sub(r"\s+", " ", text)
    for wrong, right in MISHEARINGS.items():
        text = re.sub(rf"\b{wrong}\b", right, text)
    text = _FILLERS.sub("", text)
    text = _TRAILING.sub("", text)
    return text.strip()


def needs_confirm(command: str | None) -> bool:
    return bool(command) and command.lower().lstrip("_-!") in CONFIRM_COMMANDS


# Spoken word -> the abbreviation Rhino uses inside command names, so that
# "select previous", "sel prev" and "select prev" all become "selprev" (SelPrev).
ABBREVIATIONS: dict[str, str] = {
    "select": "sel", "selection": "sel", "previous": "prev", "curve": "crv", "curves": "crv",
    "surface": "srf", "surfaces": "srf", "polysurface": "polysrf", "polysurfaces": "polysrf",
    "point": "pt", "points": "pt", "dimension": "dim", "dimensions": "dim", "object": "obj",
    "objects": "obj", "duplicate": "dup", "information": "info", "maximize": "max",
    "construction": "c", "rectangle": "rect", "extension": "ext", "direction": "dir",
    "control": "ctrl", "mesh": "mesh", "meshes": "mesh", "block": "block", "blocks": "block",
    "text": "text", "lines": "line", "polylines": "polyline", "circles": "circle",
    "one": "1", "two": "2", "three": "3",
}
# Words people say that never appear in command names ("select BY layer").
GLUE_WORDS = {"by", "the", "a", "an", "to", "of", "on", "all"}
_GLUE_KEEP = {"all"}  # ... except when the command really has it (SelAll)

FUZZY_CUTOFF = 0.86


def load_user_aliases(path: str | Path | None) -> dict[str, str]:
    """Read {"spoken phrase": "macro"} from a JSON file; missing file -> {}."""
    if not path:
        return {}
    path = Path(path).expanduser()
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {normalize(k): v for k, v in data.items() if not k.startswith("_")}


class RuleMapper:
    def __init__(self, commands: list[str] | None = None, user_aliases: dict[str, str] | None = None):
        self.aliases = {**ALIASES, **(user_aliases or {})}
        self.set_commands(commands or FALLBACK_COMMANDS)

    def set_commands(self, commands: list[str]) -> None:
        self.commands = {c.lower(): c for c in commands}
        self._keys = list(self.commands)

    def is_command(self, name: str) -> bool:
        return name.lower().lstrip("_-!") in self.commands

    # -- spoken words -> command name ---------------------------------------- #
    @staticmethod
    def _variants(words: list[str]) -> list[str]:
        raw = "".join(words)
        canon = "".join(ABBREVIATIONS.get(w, w) for w in words)
        no_glue = "".join(ABBREVIATIONS.get(w, w) for w in words
                          if w not in GLUE_WORDS or w in _GLUE_KEEP)
        no_glue_all = "".join(ABBREVIATIONS.get(w, w) for w in words if w not in GLUE_WORDS)
        out = []
        for v in (raw, canon, no_glue, no_glue_all):
            v = v.lstrip("_-")
            if v and v not in out:
                out.append(v)
        return out

    def lookup(self, words: list[str], fuzzy: bool = False) -> str | None:
        for key in self._variants(words):
            if key in self.commands:
                return self.commands[key]
        if fuzzy:
            for key in self._variants(words):
                if len(key) < 5:
                    continue
                close = difflib.get_close_matches(key, self._keys, n=1, cutoff=FUZZY_CUTOFF)
                if close:
                    return self.commands[close[0]]
        return None

    def map(self, text: str, fuzzy: bool = True) -> Match | None:
        norm = normalize(text)
        if not norm:
            return None
        if norm in self.aliases:
            macro = self.aliases[norm]
            cmd = macro.split()[0].lstrip("_-!") if macro and macro != "!" else None
            return Match(macro, "alias", cmd, needs_confirm(cmd))

        explicit = _EXPLICIT.match(norm)
        if explicit:
            norm = explicit.group(1)

        words = norm.split()
        # Exact matches first (longest run of leading words), then fuzzy ones.
        for allow_fuzzy in ((False, True) if fuzzy else (False,)):
            for n in range(min(5, len(words)), 0, -1):
                rest = words[n:]
                # Trailing words must look like command-line input (numbers, coordinates,
                # Option=Value). Anything else is a sentence for the model, unless the user
                # said "run ..." in which case it passes through untouched.
                if not explicit and not all(_ARG_TOKEN.match(w) for w in rest):
                    continue
                name = self.lookup(words[:n], fuzzy=allow_fuzzy)
                if name:
                    macro = " ".join(["_" + name, *rest])
                    return Match(macro, "command" if not allow_fuzzy else "fuzzy", name,
                                 needs_confirm(name))
        return None
