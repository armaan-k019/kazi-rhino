"""Reference lists of the components in each add-on (name, nickname, panel, inputs, outputs).

The lists in data/*.json were read from each add-on's documentation or source code. They let
Claude and the voice planner pick the right component without Rhino running. What is really
installed is always checked live through the bridge (gh_resolve) before anything is built,
and `learn` can replace these lists with a snapshot of the user's own Grasshopper.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path

LEARNED_PATH = Path(os.path.expanduser("~")) / ".kazi-rhino" / "components.json"


def norm(text: str | None) -> str:
    s = (text or "").strip().lower()
    for prefix in ("weaverbird's ", "weaverbird’s ", "wb "):
        if s.startswith(prefix):
            s = s[len(prefix):]
    return re.sub(r"[^a-z0-9]+", "", s)


@dataclass(frozen=True)
class Component:
    addon: str
    name: str
    nickname: str | None
    panel: str
    description: str
    inputs: tuple[tuple[str, str, str], ...] | None    # (name, nickname, type); None = not read
    outputs: tuple[tuple[str, str, str], ...] | None

    def to_dict(self) -> dict:
        d = {"addon": self.addon, "name": self.name, "nickname": self.nickname,
             "panel": self.panel, "description": self.description}
        if self.inputs is not None:
            d["inputs"] = [{"name": n, "nickname": k, "type": t} for n, k, t in self.inputs]
        if self.outputs is not None:
            d["outputs"] = [{"name": n, "nickname": k, "type": t} for n, k, t in self.outputs]
        return d

    def line(self) -> str:
        """One compact line for a model prompt."""
        text = self.name
        if self.inputs is not None:
            text += " (" + ", ".join(n for n, _k, _t in self.inputs) + ")"
        if self.outputs:
            text += " -> " + ", ".join(n for n, _k, _t in self.outputs)
        return text


def _params(raw) -> tuple | None:
    if raw is None:
        return None
    out = []
    for p in raw:
        p = list(p) + ["", "", ""]
        out.append((str(p[0]), str(p[1] or p[0]), str(p[2] or "")))
    return tuple(out)


class Catalog:
    def __init__(self, addons: dict[str, dict]):
        self.meta = {aid: {k: v for k, v in data.items() if k != "components"}
                     for aid, data in addons.items()}
        self.components: list[Component] = []
        for aid, data in addons.items():
            for row in data["components"]:
                row = list(row) + [None] * 6
                self.components.append(Component(aid, str(row[0]), row[1], str(row[2] or ""),
                                                 str(row[3] or ""), _params(row[4]), _params(row[5])))
        self._by_name: dict[str, list[Component]] = {}
        for c in self.components:
            self._by_name.setdefault(norm(c.name), []).append(c)
            if c.nickname and norm(c.nickname) != norm(c.name):
                self._by_name.setdefault(norm(c.nickname), []).append(c)

    def addons(self) -> list[str]:
        return sorted(self.meta)

    def of(self, addon: str) -> list[Component]:
        return [c for c in self.components if c.addon == addon]

    def find(self, name: str, addon: str | None = None) -> Component | None:
        hits = [c for c in self._by_name.get(norm(name), []) if addon in (None, c.addon)]
        if not hits:
            return None
        exact = [c for c in hits if norm(c.name) == norm(name)]
        return (exact or hits)[0]

    def search(self, query: str, addon: str | None = None, limit: int = 20) -> list[Component]:
        words = [norm(w) for w in query.split() if norm(w)]
        whole = norm(query)
        scored = []
        for order, c in enumerate(self.components):
            if addon and c.addon != addon:
                continue
            name, nick = norm(c.name), norm(c.nickname)
            rest = norm(c.description) + norm(c.panel)
            if whole and whole == name:
                s = 100
            elif whole and whole == nick:
                s = 90
            elif whole and whole in name:
                s = 60
            else:
                in_name = sum(1 for w in words if w in name or w in nick)
                in_rest = sum(1 for w in words if w in rest)
                if not words or in_name + in_rest < len(words):
                    continue
                s = 10 + 5 * in_name
            scored.append((-s, len(name), order, c))    # best score, then shortest name
        scored.sort(key=lambda t: t[:3])
        return [t[3] for t in scored[:limit]]


def _read_packaged() -> dict[str, dict]:
    out = {}
    for entry in resources.files(__package__).joinpath("data").iterdir():
        if entry.name.endswith(".json"):
            data = json.loads(entry.read_text(encoding="utf-8"))
            out[data["id"]] = data
    return out


@lru_cache(maxsize=1)
def load() -> Catalog:
    return Catalog(_read_packaged())


def load_learned(path: Path | None = None) -> dict | None:
    """The snapshot of the user's own Grasshopper written by audit.learn (None if never run)."""
    path = Path(path or LEARNED_PATH)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
