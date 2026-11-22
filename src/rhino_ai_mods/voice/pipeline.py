"""Speech text -> Rhino macro -> Rhino command line."""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import asdict, dataclass

from ..bridge_client import BridgeClient, BridgeError
from .llm import LLMMapper
from .rules import Match, RuleMapper, needs_confirm, normalize

log = logging.getLogger("rhino_voice")


@dataclass
class Outcome:
    status: str               # ran | typed_for_confirm | typed_raw | not_a_command | dry_run | error
    text: str
    macro: str | None = None
    source: str | None = None
    detail: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class VoicePipeline:
    """Map dictated text to a Rhino macro and send it to Rhino through the bridge.

    mode="rhino"   the user explicitly sent this to Rhino: rules, then the model, then (if the
                   model says it is not a command) the raw text is typed into the command line
                   without Enter, like typing into a search bar.
    mode="dictate" the user was just dictating while Rhino had focus: only clear commands are run;
                   anything else returns not_a_command so the dictation app pastes the text.
    """

    def __init__(self, bridge: BridgeClient | None = None, llm: LLMMapper | None = None,
                 dry_run: bool = False, auto_enter: bool = True, llm_in_dictate: bool = False):
        self.bridge = bridge or BridgeClient(timeout=10)
        self.rules = RuleMapper()
        self.llm = llm
        self.dry_run = dry_run
        self.auto_enter = auto_enter
        self.llm_in_dictate = llm_in_dictate
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

    # -- mapping ------------------------------------------------------------- #
    def map(self, text: str, mode: str = "rhino") -> Match | None:
        self.refresh_commands()
        match = self.rules.map(text)
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
        with self._lock:
            text = (text or "").strip()
            if not text:
                return Outcome("not_a_command", text, detail="empty")
            try:
                match = self.map(text, mode)
                if match is None:
                    if mode != "rhino":
                        return Outcome("not_a_command", text)
                    # Explicit send-to-Rhino with no command found: put the words in the command
                    # line so Rhino's autocomplete can take it from there.
                    raw = "".join(re.sub(r"\W", "", w).capitalize() for w in normalize(text).split()[:3])
                    if not self.dry_run:
                        self._send(raw, enter=False)
                    return Outcome("typed_raw" if not self.dry_run else "dry_run", text, raw, "raw")

                enter = self.auto_enter and not match.needs_confirm
                if self.dry_run:
                    return Outcome("dry_run", text, match.macro, match.source,
                                   "would press Enter" if enter else "would wait for Enter")
                self._send(match.macro, enter)
                return Outcome("ran" if enter else "typed_for_confirm", text, match.macro, match.source)
            except BridgeError as exc:
                return Outcome("error", text, detail=str(exc))
