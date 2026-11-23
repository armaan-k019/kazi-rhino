"""A stand-in for the Rhino bridge (TCP + JSON), with a small fake Grasshopper canvas."""

from __future__ import annotations

import itertools
import json
import socket
import threading


class FakeBridge:
    def __init__(self, commands=None, confirm=True, selection=1, script_errors=None):
        self.calls: list[tuple[str, dict]] = []
        self.commands = commands or ["Box", "Circle", "BooleanUnion", "Loft", "Move", "Copy",
                                     "Delete", "Undo", "Zoom", "Sphere", "Layer", "Exit",
                                     "SelPrev", "SelLast", "ExtrudeCrv"]
        self.confirm_answer = confirm
        self.selection = selection
        # successive error lists returned when the script is solved: [["boom"], []] = fails once
        self.script_errors = list(script_errors or [])
        self.objects: dict[str, dict] = {}
        self.wires: list[tuple[str, str, str]] = []
        self._ids = itertools.count(1)
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen()
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._loop, daemon=True).start()

    # -- transport ---------------------------------------------------------- #
    def _loop(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        for line in conn.makefile("rb"):
            req = json.loads(line)
            self.calls.append((req["cmd"], req["args"]))
            try:
                resp = {"id": req["id"], "ok": True, "result": self._dispatch(req["cmd"], req["args"])}
            except Exception as exc:  # noqa: BLE001
                resp = {"id": req["id"], "ok": False, "error": str(exc)}
            conn.sendall((json.dumps(resp) + "\n").encode())

    def close(self):
        self.sock.close()

    # -- helpers for tests -------------------------------------------------- #
    def macros(self):
        return [(a["macro"], a["enter"]) for c, a in self.calls if c == "run_command"]

    def cmds(self):
        return [c for c, _ in self.calls]

    # -- fake Rhino/Grasshopper -------------------------------------------- #
    def _new(self, kind, nickname, **extra):
        guid = f"guid-{next(self._ids)}"
        self.objects[guid] = {"guid": guid, "kind": kind, "nickname": nickname, **extra}
        return guid

    def _desc(self, guid, errors=()):
        o = self.objects[guid]
        return {"guid": guid, "nickname": o["nickname"], "type": o["kind"],
                "messages": [{"level": "error", "text": e} for e in errors]}

    def _dispatch(self, cmd, a):
        if cmd == "boom":
            raise RuntimeError("kaboom")
        if cmd == "list_rhino_commands":
            return {"commands": self.commands}
        if cmd == "get_selection":
            return {"count": self.selection, "objects": []}
        if cmd == "confirm":
            return {"ok": self.confirm_answer}
        if cmd == "gh_free_spot":
            return {"x": 80, "y": 200}
        if cmd == "gh_add_geometry_input":
            g = self._new("Param_Geometry", a["nickname"])
            return {**self._desc(g), "objects": self.selection}
        if cmd in ("gh_add_slider", "gh_add_toggle"):
            g = self._new(cmd[7:], a["nickname"], args=a)
            return self._desc(g)
        if cmd == "gh_create_script":
            g = self._new("Python3Component", a["nickname"], code=a["code"],
                          inputs=[i["name"] for i in a["inputs"]], outputs=a["outputs"])
            return self._desc(g)
        if cmd == "gh_update_script":
            self.objects[a["component"]]["code"] = a["code"]
            return self._desc(a["component"])
        if cmd == "gh_connect":
            tgt = self.objects[a["target"]]
            if a["target_input"] not in tgt["inputs"]:
                raise ValueError("no input " + a["target_input"])
            self.wires.append((a["source"], a["target"], a["target_input"]))
            return {"connected": True}
        if cmd == "gh_group":
            return {"group": self._new("GH_Group", a["name"], members=a["components"])}
        if cmd == "kazi_record_build":
            self.builds = getattr(self, "builds", []) + [a]
            return {"recorded": len(self.builds)}
        if cmd == "kazi_builds":
            return {"builds": getattr(self, "builds", [])}
        if cmd == "gh_get_slider":
            o = self.objects[a["component"]]
            args = o["args"]
            return {"nickname": o["nickname"], "value": o.get("value", args.get("value")),
                    "min": args.get("min"), "max": args.get("max"), "integer": bool(args.get("integer"))}
        if cmd == "gh_set_slider":
            o = self.objects[a["component"]]
            o["value"] = a["value"]
            return {"nickname": o["nickname"], "value": a["value"]}
        if cmd == "gh_solve":
            return {"problems": []}
        if cmd == "gh_read_script":
            errs = self.script_errors.pop(0) if self.script_errors else []
            return self._desc(a["component"], errs)
        return {"echo": a}
