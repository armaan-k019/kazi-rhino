"""Client for the rhino_ai_bridge.py TCP server running inside Rhino."""

from __future__ import annotations

import itertools
import json
import os
import socket
import threading
from typing import Any

DEFAULT_HOST = os.environ.get("RHINO_AI_BRIDGE_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("RHINO_AI_BRIDGE_PORT", "2010"))


class BridgeError(RuntimeError):
    """The bridge answered with an error, or could not be reached."""


class BridgeClient:
    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = 90.0):
        self.host, self.port, self.timeout = host, port, timeout
        self._sock: socket.socket | None = None
        self._file = None
        self._lock = threading.Lock()
        self._ids = itertools.count(1)

    def _connect(self) -> None:
        try:
            self._sock = socket.create_connection((self.host, self.port), timeout=5)
        except OSError as exc:
            raise BridgeError(
                f"Can't reach the Rhino bridge at {self.host}:{self.port}. In Rhino, run KaziStart "
                '(or _-ScriptEditor _Run "<path>/bridge/rhino_ai_bridge.py") first.'
            ) from exc
        self._sock.settimeout(self.timeout)
        self._file = self._sock.makefile("rb")

    def close(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            finally:
                self._sock, self._file = None, None

    def call(self, cmd: str, **args: Any) -> Any:
        """Send one command and return its result. Reconnects once if the socket dropped."""
        with self._lock:
            for attempt in (1, 2):
                if self._sock is None:
                    self._connect()
                req_id = next(self._ids)
                payload = json.dumps({"id": req_id, "cmd": cmd, "args": args}) + "\n"
                try:
                    self._sock.sendall(payload.encode("utf-8"))
                    line = self._file.readline()
                    if not line:
                        raise ConnectionError("bridge closed the connection")
                except (OSError, ConnectionError):
                    self.close()
                    if attempt == 2:
                        raise BridgeError("Lost connection to the Rhino bridge") from None
                    continue
                resp = json.loads(line)
                if not resp.get("ok"):
                    raise BridgeError(resp.get("error", "unknown bridge error"))
                return resp.get("result")
        raise BridgeError("unreachable")
