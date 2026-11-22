"""`rhino-voice`: HTTP endpoint + CLI for the voice-to-Rhino pipeline.

HTTP contract (used by the hushtype dictation app, but any tool can POST to it):

    POST http://127.0.0.1:8765/dictation
    {"text": "boolean union", "app": "Rhinoceros", "source": "hushtype", "mode": "rhino" | "dictate"}

Responses (the dictation app pastes the text itself on any non-2xx):
    200  handled now                    {"status": "ran" | "typed_for_confirm" | "typed_raw", "macro": ...}
    202  accepted, the model is mapping it in the background
    409  not a Rhino command ("dictate" mode only), so the app should paste it
    503  Rhino or the bridge is not reachable
    GET /health -> 200 {"ok": true}
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .llm import LLMMapper, make_backend
from .pipeline import Outcome, VoicePipeline

log = logging.getLogger("rhino_voice")


def make_handler(pipeline: VoicePipeline):
    class Handler(BaseHTTPRequestHandler):
        server_version = "rhino-voice/0.1"

        def log_message(self, fmt, *args):  # route to logging instead of stderr spam
            log.debug("%s - " + fmt, self.address_string(), *args)

        def _reply(self, code: int, body: dict) -> None:
            data = json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            if self.path.rstrip("/") == "/health":
                self._reply(200, {"ok": True})
            else:
                self._reply(404, {"error": "not found"})

        def do_POST(self):  # noqa: N802
            if self.path.rstrip("/") != "/dictation":
                self._reply(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                text = str(body.get("text") or "")
                mode = body.get("mode") or "rhino"
            except (ValueError, json.JSONDecodeError):
                self._reply(400, {"error": "expected JSON {text, mode}"})
                return
            log.info("[%s] %r", mode, text)

            # Rules are instant, so try them inline. If they fail and a model is needed, answer
            # 202 right away (the dictation app only waits ~2 s) and finish in the background.
            pipeline.refresh_commands()
            quick = pipeline.rules.map(text)
            if quick is None and mode == "rhino" and pipeline.llm is not None:
                threading.Thread(target=_run_and_log, args=(pipeline, text, mode), daemon=True).start()
                self._reply(202, {"status": "accepted", "text": text})
                return

            outcome = pipeline.handle(text, mode)
            _log_outcome(outcome)
            code = {"not_a_command": 409, "error": 503}.get(outcome.status, 200)
            self._reply(code, outcome.to_dict())

    return Handler


def _log_outcome(outcome: Outcome) -> None:
    if outcome.status == "error":
        log.error("%r -> error: %s", outcome.text, outcome.detail)
    else:
        log.info("%r -> %s %s (%s)", outcome.text, outcome.status, outcome.macro or "", outcome.source or "-")


def _run_and_log(pipeline: VoicePipeline, text: str, mode: str) -> None:
    _log_outcome(pipeline.handle(text, mode))


def build_pipeline(args) -> VoicePipeline:
    backend = make_backend(args.llm, args.model)
    return VoicePipeline(llm=LLMMapper(backend) if backend else None, dry_run=args.dry_run,
                         auto_enter=not args.no_enter, llm_in_dictate=args.llm_in_dictate)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rhino-voice", description="Voice / text to Rhino commands")
    parser.add_argument("--llm", default="hf-local", choices=["hf-local", "hf-api", "none"],
                        help="model backend for free-form speech (default: hf-local)")
    parser.add_argument("--model", help="Hugging Face model id (default depends on backend)")
    parser.add_argument("--dry-run", action="store_true", help="print macros instead of sending them")
    parser.add_argument("--no-enter", action="store_true",
                        help="never press Enter; always leave the macro for you to confirm")
    parser.add_argument("--llm-in-dictate", action="store_true",
                        help="also use the model for 'dictate' mode (needs a fast GPU)")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    serve = sub.add_parser("serve", help="listen for dictation on HTTP")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)

    say = sub.add_parser("say", help="map one phrase and send it to Rhino")
    say.add_argument("text", nargs="+")

    sub.add_parser("repl", help="type phrases interactively (one per line)")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    pipeline = build_pipeline(args)

    if args.cmd == "say":
        outcome = pipeline.handle(" ".join(args.text), "rhino")
        print(json.dumps(outcome.to_dict(), indent=2))
        return 0 if outcome.status != "error" else 1

    if args.cmd == "repl":
        print("Type what you'd say. Ctrl+D to quit.")
        for line in sys.stdin:
            print(json.dumps(pipeline.handle(line, "rhino").to_dict()))
        return 0

    httpd = ThreadingHTTPServer((args.host, args.port), make_handler(pipeline))
    threading.Thread(target=pipeline.refresh_commands, daemon=True).start()
    if pipeline.llm is not None and args.llm == "hf-local":
        # Warm the model so the first command isn't slow.
        threading.Thread(target=lambda: pipeline.llm.map("undo"), daemon=True).start()
    log.info("rhino-voice listening on http://%s:%d/dictation (llm=%s%s)", args.host, args.port,
             args.llm, ", dry run" if args.dry_run else "")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
