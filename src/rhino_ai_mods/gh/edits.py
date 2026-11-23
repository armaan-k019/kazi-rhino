"""Voice edits to the last Grasshopper build: "more cells", "make the frame thinner",
"set floors to 20", "flip the fins", "new layout", "undo that", "bake it".

Slider and toggle edits are applied straight away (they are small and "undo that" reverts them)
and reported on Rhino's command line. Edits that need new code go to the model and show the
same Yes/No dialog as a new build.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from ..bridge_client import BridgeClient

log = logging.getLogger("rhino_voice")

# words -> (kind, direction). kind "count" = how many, "size" = how big.
_MORE = {"more": ("count", 1), "increase": ("count", 1), "add": ("count", 1), "extra": ("count", 1),
         "denser": ("count", 1),
         "fewer": ("count", -1), "less": ("count", -1), "reduce": ("count", -1), "remove": ("count", -1),
         "decrease": ("count", -1), "sparser": ("count", -1),
         "bigger": ("size", 1), "larger": ("size", 1), "wider": ("size", 1), "thicker": ("size", 1),
         "deeper": ("size", 1), "taller": ("size", 1), "higher": ("size", 1), "longer": ("size", 1),
         "stronger": ("size", 1), "heavier": ("size", 1), "fatter": ("size", 1), "chunkier": ("size", 1),
         "smaller": ("size", -1), "thinner": ("size", -1), "narrower": ("size", -1),
         "shallower": ("size", -1), "shorter": ("size", -1), "lower": ("size", -1), "weaker": ("size", -1),
         "lighter": ("size", -1), "slimmer": ("size", -1), "skinnier": ("size", -1), "tighter": ("size", -1)}
_STRENGTH = [(r"\b(?:a lot|lots|much|way|loads|significantly)\b", 1.6),
             (r"\b(?:a (?:little )?bit|slightly|a little|a touch|tiny bit)\b", 1.1)]
_DEFAULT_STEP = 1.25

# Per-recipe nouns: noun -> {kind or "*": [(param, sign), ...]}
_ALL = "*"
VOCAB: dict[str, dict[str, dict[str, list[tuple[str, int]]]]] = {
    "voronoi_facade": {
        "cell": {_ALL: [("count", 1)]}, "piece": {_ALL: [("count", 1)]},
        "opening": {"count": [("count", 1)], "size": [("frame", -1)]},
        "hole": {"count": [("count", 1)], "size": [("frame", -1)]},
        "frame": {_ALL: [("frame", 1)]}, "mullion": {_ALL: [("frame", 1)]}, "border": {_ALL: [("frame", 1)]},
    },
    "attractor_openings": {
        "opening": {"count": [("columns", 1), ("rows", 1)], "size": [("max_size", 1), ("min_size", 1)]},
        "hole": {"count": [("columns", 1), ("rows", 1)], "size": [("max_size", 1), ("min_size", 1)]},
        "column": {_ALL: [("columns", 1)]}, "row": {_ALL: [("rows", 1)]},
        "attractor": {_ALL: [("falloff", 1)]}, "effect": {_ALL: [("falloff", 1)]},
        "influence": {_ALL: [("falloff", 1)]}, "reach": {_ALL: [("falloff", 1)]},
        "contrast": {_ALL: [("max_size", 1), ("min_size", -1)]},
        "side": {_ALL: [("sides", 1)]},
    },
    "fins": {
        "fin": {"count": [("count", 1)], "size": [("depth", 1)]},
        "louvre": {"count": [("count", 1)], "size": [("depth", 1)]},
        "louver": {"count": [("count", 1)], "size": [("depth", 1)]},
        "blade": {"count": [("count", 1)], "size": [("depth", 1)]},
        "slat": {"count": [("count", 1)], "size": [("depth", 1)]},
        "depth": {_ALL: [("depth", 1)]}, "angle": {_ALL: [("rotation", 1)]},
        "rotation": {_ALL: [("rotation", 1)]}, "degree": {_ALL: [("rotation", 1)]},
        "twist": {_ALL: [("twist_range", 1)]},
    },
    "panels": {
        "panel": {"count": [("columns", 1), ("rows", 1)], "size": [("columns", -1), ("rows", -1)]},
        "tile": {"count": [("columns", 1), ("rows", 1)], "size": [("columns", -1), ("rows", -1)]},
        "joint": {_ALL: [("gap", 1)]}, "gap": {_ALL: [("gap", 1)]},
        "column": {_ALL: [("columns", 1)]}, "row": {_ALL: [("rows", 1)]},
    },
    "diagrid": {
        "diamond": {"count": [("bays", 1), ("levels", 1)], "size": [("bays", -1), ("levels", -1)]},
        "bay": {_ALL: [("bays", 1)]}, "level": {_ALL: [("levels", 1)]},
        "member": {"count": [("bays", 1), ("levels", 1)], "size": [("radius", 1)]},
        "structure": {"size": [("radius", 1)], "count": [("bays", 1), ("levels", 1)]},
        "pipe": {_ALL: [("radius", 1)]}, "radius": {_ALL: [("radius", 1)]},
    },
    "stepped_massing": {
        "floor": {_ALL: [("floors", 1)]}, "storey": {_ALL: [("floors", 1)]},
        "story": {_ALL: [("floors", 1)]}, "storie": {_ALL: [("floors", 1)]},
        "building": {"size": [("floors", 1)]}, "tower": {"size": [("floors", 1)]},
        "setback": {_ALL: [("setback", 1)]}, "step": {"size": [("setback", 1)], "count": [("step_every", -1)]},
        "tier": {"count": [("step_every", -1)], "size": [("step_every", 1)]},
        "terrace": {"size": [("setback", 1)], "count": [("step_every", -1)]},
        "floor height": {_ALL: [("floor_height", 1)]}, "floor to floor": {_ALL: [("floor_height", 1)]},
    },
}

# toggles: phrase -> (toggle, value or None = flip)
TOGGLE_PHRASES = [
    (r"\bflip\b|\bother side\b|\boutside\b|\binside\b", "flip", None),
    (r"\b(?:no|without|remove the|turn off(?: the)?) stagger|\bstraight (?:rows|grid)\b|\bstack bond\b", "stagger", False),
    (r"\bstagger|\brunning bond|\bbrick bond|\bbrick ?work", "stagger", True),
    (r"\bhorizontal\b|\blouv", "horizontal", True),
    (r"\bvertical\b", "horizontal", False),
    (r"\binvert\b|\breverse\b|\bopposite\b|\bother way round\b", "invert", None),
    (r"\b(?:no|without|remove the|turn off(?: the)?) ring beams?\b", "ring_beams", False),
    (r"\bring beams?\b", "ring_beams", True),
]
SHUFFLE = re.compile(r"\b(?:shuffle|randomi[sz]e|re-?roll|new (?:seed|layout|pattern|arrangement)|"
                     r"different (?:seed|layout|pattern|arrangement)|another (?:layout|pattern|one))\b")
UNDO = re.compile(r"^(?:undo|go back|revert|put it back|undo (?:that|it|the last (?:change|edit)))$")
UNDO_BUILD = re.compile(r"\b(?:undo|delete|remove|scrap|get rid of|throw away)\b.*\b(?:build|definition|that whole thing)\b"
                        r"|^(?:scrap|delete|remove) (?:it|that)$")
# edits that need code, not sliders: "make the openings circular", "add a random rotation"
CODE_EDIT = re.compile(r"^(?:please\s+)?(?:make|change|turn|add|remove|use|instead|replace|let|have|give|"
                       r"can you|could you|only|also|swap|rotate|align|offset|scale|split|join|cap|round)\b")
BAKE = re.compile(r"^(?:please\s+)?bake\b")
MOVE = re.compile(r"\bmove (?:the )?attractor (?:a (?:little )?bit |slightly |a lot |way )?"
                  r"(up|down|left|right|higher|lower|to the (?:left|right|top|bottom|middle|centre|center))")
SET = re.compile(r"\b(?:set|make|change|put|turn)\s+(?:the\s+)?(.+?)\s+(?:to|at|=|equal to)\s+(-?\d+(?:\.\d+)?)")
NUMBER_NOUN = re.compile(r"(?<![\w.])(-?\d+(?:\.\d+)?)\s+([a-z][a-z ]*?)(?:s)?\b(?=$|[ ,.])")


@dataclass
class Change:
    kind: str                  # slider | toggle
    name: str
    guid: str
    old: float | bool
    new: float | bool

    def text(self) -> str:
        if self.kind == "toggle":
            return f"{self.name} {'on' if self.new else 'off'}"
        return f"{self.name} {_fmt(self.old)} → {_fmt(self.new)}"


@dataclass
class EditResult:
    status: str                # edited | undone | baked | removed | no_build | not_an_edit | error
    title: str = ""
    changes: list[Change] = field(default_factory=list)
    detail: str = ""

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["changes"] = [c.__dict__ for c in self.changes]
        return d


def _fmt(v) -> str:
    return f"{v:g}" if isinstance(v, float) else str(v)


def _singular(word: str) -> str:
    w = word.strip()
    for suf, rep in (("ies", "y"), ("ves", "f"), ("s", "")):
        if w.endswith(suf) and len(w) > 3 and not w.endswith("ss"):
            return w[: -len(suf)] + rep
    return w


def _strength(text: str) -> float:
    for pat, f in _STRENGTH:
        if re.search(pat, text):
            return f
    return _DEFAULT_STEP


class Editor:
    """Applies spoken edits to the most recent kazi build through the bridge."""

    def __init__(self, bridge: BridgeClient, planner=None, confirm: bool = True):
        self.bridge = bridge
        self.planner = planner          # for edits that need new code (needs a model)
        self.confirm = confirm
        self.history: list = []          # list of [Change] or ("code", script, old_code)

    # -- helpers --------------------------------------------------------------- #
    def last_build(self) -> dict | None:
        builds = self.bridge.call("kazi_builds").get("builds", [])
        return builds[-1] if builds else None

    def say(self, text: str) -> None:
        try:
            self.bridge.call("rhino_message", text=text)
        except Exception:  # noqa: BLE001
            pass

    def _params(self, build: dict) -> tuple[dict, dict]:
        return dict(build.get("sliders") or {}), dict(build.get("toggles") or {})

    def _resolve(self, noun: str, kind: str | None, build: dict) -> list[tuple[str, int]]:
        """A spoken noun phrase -> slider names (with sign) in this build."""
        sliders, toggles = self._params(build)
        names = set(sliders)
        noun = re.sub(r"\b(?:the|a|an|some|of|it|its|them|those|these)\b", " ", noun).strip()
        noun = re.sub(r"\s+", " ", noun)
        if not noun:
            return []
        # exact slider name, spaces for underscores ("floor height", "max size")
        key = noun.replace(" ", "_")
        if key in names:
            return [(key, 1)]
        vocab = VOCAB.get(build.get("recipe") or "", {})
        words = noun.split()
        candidates = [noun, _singular(noun)] + [_singular(w) for w in reversed(words)]
        for cand in candidates:
            entry = vocab.get(cand)
            if entry:
                hits = entry.get(kind or "", []) or entry.get(_ALL, []) or next(iter(entry.values()))
                hits = [(n, s) for n, s in hits if n in names]
                if hits:
                    return hits
        for cand in candidates:   # a slider whose name contains the word ("height" -> floor_height)
            hits = [(n, 1) for n in names if cand and cand in n.split("_")]
            if len(hits) == 1:
                return hits
        return []

    # -- parsing --------------------------------------------------------------- #
    def plan(self, text: str, build: dict) -> list[tuple[str, str, object]]:
        """Text -> [(kind, name, op)] where op is ("set", v) | ("scale", f, sign) | ("add", d) | ("toggle", v)."""
        t = text.lower().strip().rstrip(".!?")
        sliders, toggles = self._params(build)
        ops: list[tuple[str, str, object]] = []

        for m in SET.finditer(t):
            for name, _sign in self._resolve(m.group(1), None, build)[:1]:
                ops.append(("slider", name, ("set", float(m.group(2)))))
        if not ops:
            for m in NUMBER_NOUN.finditer(t):
                for name, _sign in self._resolve(m.group(2), None, build)[:1]:
                    ops.append(("slider", name, ("set", float(m.group(1)))))
        if ops:
            return ops

        if SHUFFLE.search(t) and "seed" in sliders:
            return [("slider", "seed", ("add", 1))]

        mv = MOVE.search(t)
        if mv and {"attractor_x", "attractor_y"} & set(sliders):
            d = 0.25 if re.search(r"a lot|way", t) else 0.05 if re.search(r"bit|slightly", t) else 0.15
            where = mv.group(1)
            if where in ("up", "higher") or "top" in where:
                return [("slider", "attractor_y", ("add", d))]
            if where in ("down", "lower") or "bottom" in where:
                return [("slider", "attractor_y", ("add", -d))]
            if "left" in where:
                return [("slider", "attractor_x", ("add", -d))]
            if "right" in where:
                return [("slider", "attractor_x", ("add", d))]
            return [("slider", "attractor_x", ("set", 0.5)), ("slider", "attractor_y", ("set", 0.5))]

        rot = re.search(r"\b(?:rotate|turn|angle|tilt)\b", t)
        if rot and "rotation" in sliders and not re.search(r"\btwist", t):
            back = re.search(r"\b(?:less|back|other way|counter|anti|reduce)\b", t)
            d = 15.0 * (2 if _strength(t) > 1.5 else 0.33 if _strength(t) < 1.2 else 1)
            return [("slider", "rotation", ("add", -d if back else d))]

        if re.search(r"\b(?:double|twice as many|twice the)\b", t) or re.search(r"\b(?:halve|half (?:as|the))\b", t):
            factor = 2.0 if re.search(r"double|twice", t) else 0.5
            noun = re.sub(r".*\b(?:double|twice as many|twice the|halve|half as many|half the|half as)\b", "", t)
            for name, sign in self._resolve(noun, "count", build):
                ops.append(("slider", name, ("scale", factor ** sign, 1)))
            if ops:
                return ops

        # "more cells", "make the frame thinner", "deeper fins", "increase the setback a bit"
        for word, (kind, direction) in _MORE.items():
            m = re.search(rf"\b{word}\b", t)
            if not m:
                continue
            before, after = t[: m.start()], t[m.end():]
            noun = re.sub(r"^(?:please|can you|could you|make|let'?s|go|give me|get)\b", "", after.strip())
            noun = re.sub(r"\b(?:a (?:little )?bit|slightly|a lot|lots|much|way|please)\b", "", noun)
            hits = self._resolve(noun, kind, build) if noun.strip() else []
            if not hits:   # "make the frame thinner": noun comes first
                noun = re.sub(r"^(?:please|can you|could you)?\s*(?:make|let'?s make|have|set)?\s*", "", before)
                noun = re.sub(r"\b(?:a (?:little )?bit|slightly|a lot|lots|much|way)\b", "", noun)
                hits = self._resolve(noun, kind, build)
            f = _strength(t)
            for name, sign in hits:
                ops.append(("slider", name, ("scale", f, direction * sign)))
            if ops:
                return ops

        for pat, name, value in TOGGLE_PHRASES:
            if name in toggles and re.search(pat, t):
                return [("toggle", name, ("toggle", value))]
        return []

    # -- applying -------------------------------------------------------------- #
    def handle(self, text: str) -> EditResult:
        t = text.lower().strip().rstrip(".!?")
        if UNDO.match(t) and not UNDO_BUILD.search(t):
            return self.undo()
        build = self.last_build()
        if build is None:
            return EditResult("no_build", detail="nothing built yet, say 'build ...' first")
        title = build.get("title", "")
        if UNDO_BUILD.search(t):
            res = self.bridge.call("confirm", title="kazi", message=f"Remove '{title}' from Grasshopper?")
            if not res.get("ok"):
                return EditResult("cancelled", title)
            out = self.bridge.call("kazi_undo_build")
            self.history.clear()
            return EditResult("removed", title, detail=f"{out.get('removed', 0)} components")
        if BAKE.search(t):
            out = self.bridge.call("kazi_bake")
            return EditResult("baked", title, detail=str(out.get("baked")))
        ops = self.plan(t, build)
        if not ops:
            if self.planner is not None and getattr(self.planner, "backend", None) is not None \
                    and CODE_EDIT.search(t):
                return self.edit_code(text, build)
            return EditResult("not_an_edit", title)
        sliders, toggles = self._params(build)
        changes = []
        for kind, name, op in ops:
            if kind == "toggle":
                guid = toggles[name]
                cur = bool(self.bridge.call("gh_toggle", component=guid).get("value"))
                new = (not cur) if op[1] is None else bool(op[1])
                if new != cur:
                    self.bridge.call("gh_toggle", component=guid, value=new)
                    changes.append(Change("toggle", name, guid, cur, new))
                continue
            guid = sliders[name]
            info = self.bridge.call("gh_get_slider", component=guid)
            cur = float(info["value"])
            new = _apply(op, cur, info)
            if new != cur:
                self.bridge.call("gh_set_slider", component=guid, value=new)
                changes.append(Change("slider", name, guid, cur, new))
        if not changes:
            self.say(f"{title}: already at the limit")
            return EditResult("edited", title, detail="no change (at the limit)")
        self.history.append(changes)
        self.say(f"{title}: " + ", ".join(c.text() for c in changes) + "   (say 'undo' to go back)")
        return EditResult("edited", title, changes)

    def edit_code(self, text: str, build: dict) -> EditResult:
        title, script = build.get("title", ""), build.get("script")
        info = self.bridge.call("gh_read_script", component=script)
        code = info.get("code") or ""
        def pname(p):   # script variables are the params' nicknames
            return (p.get("nickname") or p.get("name")) if isinstance(p, dict) else str(p)
        ins = [pname(p) for p in info.get("inputs", [])]
        outs = [pname(p) for p in info.get("outputs", []) if pname(p) != "out"]
        self.say(f"{title}: asking the model to change the script...")
        new_code = self.planner.edit_code(code, text, ins, outs)
        if not new_code or new_code.strip() == code.strip():
            return EditResult("error", title, detail="the model didn't return a changed script")
        if self.confirm:
            ok = self.bridge.call("confirm", title=f"kazi: change '{title}'",
                                  message=f"Change the script of '{title}':\n\n{text}\n\nApply?")
            if not ok.get("ok"):
                return EditResult("cancelled", title)
        self.bridge.call("gh_update_script", component=script, code=new_code, recompute=False)
        self.bridge.call("gh_solve")
        after = self.bridge.call("gh_read_script", component=script)
        errors = [m["text"] for m in after.get("messages", []) if m["level"] == "error"]
        if errors:
            self.bridge.call("gh_update_script", component=script, code=code, recompute=True)
            self.say(f"{title}: the change errored, kept the old script ({errors[0]})")
            return EditResult("error", title, detail="change reverted: " + "; ".join(errors))
        self.history.append(("code", script, code))
        self.say(f"{title}: script changed   (say 'undo' to go back)")
        return EditResult("edited", title, detail="script changed by the model")

    def undo(self) -> EditResult:
        if not self.history:
            return EditResult("not_an_edit", detail="no voice edit to undo")
        changes = self.history.pop()
        if isinstance(changes, tuple):
            _, script, old = changes
            self.bridge.call("gh_update_script", component=script, code=old, recompute=True)
            self.say("undid the script change")
            return EditResult("undone", detail="script restored")
        for c in reversed(changes):
            if c.kind == "toggle":
                self.bridge.call("gh_toggle", component=c.guid, value=c.old)
            else:
                self.bridge.call("gh_set_slider", component=c.guid, value=c.old)
        self.say("undid: " + ", ".join(c.text() for c in changes))
        return EditResult("undone", changes=changes)


def _apply(op, cur: float, info: dict) -> float:
    lo, hi = info.get("min"), info.get("max")
    integer = bool(info.get("integer"))
    if op[0] == "set":
        new = op[1]
    elif op[0] == "add":
        new = cur + op[1]
        if lo is not None and hi is not None and hi - lo <= 1.0 + 1e-9:   # 0-1 sliders stay inside
            new = min(max(new, lo), hi)
    else:
        _, f, direction = op
        step = f if direction > 0 else 1.0 / f
        if cur == 0 and direction > 0:
            span = (hi - lo) if (lo is not None and hi is not None) else 1.0
            new = span * 0.1
        else:
            new = cur * step if cur >= 0 else cur / step
        if integer and round(new) == cur:
            new = cur + (1 if direction > 0 else -1)
        if direction < 0 and lo is not None:
            new = max(new, lo)            # don't shrink below the slider's minimum
    if integer:
        new = float(round(new))
    return round(new, 6)
