"""Speech text -> Rhino command line, or -> a Grasshopper definition."""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import asdict, dataclass

from ..bridge_client import BridgeClient, BridgeError
from .llm import LLMMapper
from .rules import Match, RuleMapper, needs_confirm, normalize

log = logging.getLogger("rhino_voice")

# "build me a voronoi script ...", "make a grasshopper definition that ...", "in grasshopper, ..."
_GH_VERB = r"(?:build|create|make|generate|give me|set up|write|design|script)"
_GH_NOUN = (r"(?:grasshopper|script|definition|component|voronoi|stepping|stepped|parametric|"
            r"attractor|pattern|panelli[sz]|louv(?:re|er)s?|fins|tessellat|lattice|massing|terrac)")
GH_REQUEST = re.compile(rf"^(?:(?:please|can you|could you|let'?s)\s+)?{_GH_VERB}\b.*\b{_GH_NOUN}"
                        rf"|\bin grasshopper\b|^grasshopper[, ]")


# a brand-new build, as opposed to an edit of the last one ("more cells", "make the frame thinner")
NEW_BUILD = re.compile(r"^(?:(?:please|can you|could you|let'?s|now)\s+)?(?:build|create|generate|design|"
                       r"set up|write|give me|make (?:me )?(?:a|an|some|another)\b|add (?:a|an|some)\b|"
                       r"put (?:a|an|some)\b|start (?:a|an)\b|new (?:grasshopper|definition|build|script)\b)")


def is_new_build(text: str) -> bool:
    return bool(NEW_BUILD.search(normalize(text)))


def is_grasshopper_request(text: str) -> bool:
    return bool(GH_REQUEST.search(normalize(text)))


@dataclass
class Outcome:
    # ran | typed_for_confirm | typed_raw | not_a_command | dry_run | error
    # | built | built_with_errors | cancelled
    status: str
    text: str
    macro: str | None = None
    source: str | None = None
    detail: str | None = None
    build: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class VoicePipeline:
    """Map dictated text to Rhino and send it through the bridge.

    mode="rhino"        explicit send-to-Rhino. Rhino command (rules, fuzzy, then model). If
                        nothing matches, the words are typed into the command line without Enter.
                        Requests like "build a voronoi script ..." go to Grasshopper.
    mode="grasshopper"  always a Grasshopper build.
    mode="dictate"      user was dictating while Rhino had focus: only exact commands run,
                        anything else is not_a_command so the dictation app pastes it.

    Confirmation: by default nothing runs by itself. Commands are typed into Rhino's command
    line and wait for Enter (Esc cancels). Grasshopper builds show a Yes/No dialog first.
    """

    def __init__(self, bridge: BridgeClient | None = None, llm: LLMMapper | None = None,
                 dry_run: bool = False, auto_enter: bool = False, llm_in_dictate: bool = False,
                 builder=None, planner=None, user_aliases: dict | None = None, editor=None):
        self.bridge = bridge or BridgeClient(timeout=10)
        self.rules = RuleMapper(user_aliases=user_aliases)
        self.llm = llm
        self.dry_run = dry_run
        self.auto_enter = auto_enter
        self.llm_in_dictate = llm_in_dictate
        self.builder = builder
        self.planner = planner
        self.editor = editor
        self._commands_loaded = False
        self._lock = threading.Lock()

    # -- Rhino command list -------------------------------------------------- #
    def refresh_commands(self) -> None:
        if self._commands_loaded or self.dry_run:
            return
        try:
            cmds = self.bridge.call("list_rhino_commands")["commands"]
            if cmds:
                self.rules.set_commands(cmds)
                self._commands_loaded = True
                log.info("loaded %d Rhino command names", len(cmds))
        except BridgeError as exc:
            log.warning("could not load Rhino commands, using built-in list: %s", exc)

    # -- routing ------------------------------------------------------------- #
    def route(self, text: str, mode: str) -> str:
        """'grasshopper' | 'rhino'"""
        if mode == "grasshopper":
            return "grasshopper"
        if mode == "rhino" and is_grasshopper_request(text):
            return "grasshopper"
        return "rhino"

    # -- mapping ------------------------------------------------------------- #
    def map(self, text: str, mode: str = "rhino") -> Match | None:
        self.refresh_commands()
        match = self.rules.map(text, fuzzy=mode != "dictate")
        if match:
            return match
        if self.llm is None or (mode == "dictate" and not self.llm_in_dictate):
            return None
        result = self.llm.map(text, sorted(self.rules.commands.values()))
        log.info("model reply: %s", result.raw.strip())
        if not result.is_command:
            return None
        first = result.macro.split()[0]
        if not self.rules.is_command(first):
            log.warning("model invented an unknown command %r; ignoring", first)
            return None
        cmd = self.rules.commands[first.lower().lstrip("_-!")]
        return Match(result.macro, "llm", cmd, needs_confirm(cmd))

    # -- running ------------------------------------------------------------- #
    def _send(self, macro: str, enter: bool) -> None:
        self.bridge.call("run_command", macro=macro, enter=enter, mode="keystrokes",
                         allow_empty=True)

    def handle(self, text: str, mode: str = "rhino") -> Outcome:
        text = (text or "").strip()
        if not text:
            return Outcome("not_a_command", text, detail="empty")
        if self.route(text, mode) == "grasshopper":
            return self.handle_grasshopper(text)
        with self._lock:
            try:
                return self._handle_rhino(text, mode)
            except BridgeError as exc:
                return Outcome("error", text, detail=str(exc))

    def _handle_rhino(self, text: str, mode: str) -> Outcome:
        match = self.map(text, mode)
        if match is None:
            if mode != "rhino":
                return Outcome("not_a_command", text)
            # Explicit send-to-Rhino with no command found: put the words in the command line
            # so Rhino's autocomplete can take it from there.
            raw = "".join(re.sub(r"\W", "", w).capitalize() for w in normalize(text).split()[:3])
            if self.dry_run:
                return Outcome("dry_run", text, raw, "raw", "would type without Enter")
            self._send(raw, enter=False)
            return Outcome("typed_raw", text, raw, "raw")

        enter = self.auto_enter and not match.needs_confirm
        if self.dry_run:
            return Outcome("dry_run", text, match.macro, match.source,
                           "would press Enter" if enter else "would wait for Enter")
        self._send(match.macro, enter)
        return Outcome("ran" if enter else "typed_for_confirm", text, match.macro, match.source)

    def handle_grasshopper(self, text: str) -> Outcome:
        if self.editor is not None and not self.dry_run and not is_new_build(text):
            try:
                res = self.editor.handle(text)
            except BridgeError as exc:
                return Outcome("error", text, source="edit", detail=str(exc))
            if res.status not in ("not_an_edit", "no_build"):
                detail = res.title + ": " + (", ".join(c.text() for c in res.changes) or res.detail)
                return Outcome(res.status, text, source="edit", detail=detail, build=res.to_dict())
        if self.planner is None:
            return Outcome("error", text, source="grasshopper", detail="Grasshopper building is off")
        try:
            plan = self.planner.plan(text)
        except (LookupError, ValueError) as exc:
            return Outcome("error", text, source="grasshopper", detail=str(exc))
        if self.dry_run or self.builder is None:
            return Outcome("dry_run", text, source=plan.recipe or "model",
                           detail=plan.title + ": " + plan.summary, build=plan.to_dict())
        try:
            res = self.builder.build(plan)
        except BridgeError as exc:
            return Outcome("error", text, source="grasshopper", detail=str(exc))
        return Outcome(res.status, text, source=plan.recipe or "model",
                       detail=plan.title, build=res.to_dict())
