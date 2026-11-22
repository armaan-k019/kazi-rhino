"""A stand-in for the Rhino bridge, for tests and for trying the pipeline without Rhino."""

from __future__ import annotations

import json
import socket
import threading


class FakeBridge:
    def __init__(self, commands=None):
        self.calls: list[tuple[str, dict]] = []
        self.commands = commands or ["Box", "Circle", "BooleanUnion", "Loft", "Move", "Copy",
                                     "Delete", "Undo", "Zoom", "Sphere", "Layer", "Exit"]
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen()
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        f = conn.makefile("rb")
        for line in f:
            req = json.loads(line)
            self.calls.append((req["cmd"], req["args"]))
            if req["cmd"] == "list_rhino_commands":
                result = {"commands": self.commands}
            elif req["cmd"] == "boom":
                conn.sendall((json.dumps({"id": req["id"], "ok": False, "error": "kaboom"}) + "\n").encode())
                continue
            else:
                result = {"echo": req["args"]}
            conn.sendall((json.dumps({"id": req["id"], "ok": True, "result": result}) + "\n").encode())

    def close(self):
        self.sock.close()

    def macros(self):
        return [(a["macro"], a["enter"]) for c, a in self.calls if c == "run_command"]
