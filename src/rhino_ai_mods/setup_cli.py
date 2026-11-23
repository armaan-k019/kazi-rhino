"""`kazi-setup`: wire kazi-rhino into Claude Desktop, Claude Code and Windows startup.

    kazi-setup                 # do everything that applies on this machine
    kazi-setup --dry-run       # show what would change
    kazi-setup --no-autostart  # don't start rhino-voice when Windows starts

What it does:
1. Claude Desktop: adds the `rhino` (rhinomcp) and `rhino-ai-mods` MCP servers to
   claude_desktop_config.json, keeping everything else and saving a .bak copy first.
2. Claude Code: `claude mcp add --scope user` for both servers, if the `claude` CLI exists.
3. Windows: a `kazi-voice.cmd` in your Startup folder that starts `rhino-voice serve` minimized.
4. Prints the one Rhino step: run bridge/install_in_rhino.py once (adds the Kazi* commands).
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[2]


def desktop_config_path() -> pathlib.Path:
    if sys.platform == "win32":
        return pathlib.Path(os.environ["APPDATA"]) / "Claude" / "claude_desktop_config.json"
    if sys.platform == "darwin":
        return pathlib.Path.home() / "Library/Application Support/Claude/claude_desktop_config.json"
    return pathlib.Path.home() / ".config/Claude/claude_desktop_config.json"


def startup_dir() -> pathlib.Path | None:
    if sys.platform != "win32":
        return None
    return pathlib.Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup"


def server_entries(python: str, uvx: str | None) -> dict:
    entries = {"rhino-ai-mods": {"command": python, "args": ["-m", "rhino_ai_mods.mcp_server"]}}
    if uvx:
        entries["rhino"] = {"command": uvx, "args": ["rhinomcp@latest"]}
    return entries


def merge_desktop_config(path: pathlib.Path, entries: dict, dry_run: bool = False) -> list[str]:
    """Add/update our servers; never touch other servers or settings. Returns change notes."""
    notes = []
    config = {}
    if path.exists():
        text = path.read_text(encoding="utf-8").strip()
        config = json.loads(text) if text else {}
    servers = config.setdefault("mcpServers", {})
    for name, entry in entries.items():
        if name == "rhino" and "rhino" in servers:
            notes.append("kept your existing 'rhino' server")
            continue
        if servers.get(name) != entry:
            notes.append(("updated" if name in servers else "added") + f" '{name}'")
            servers[name] = entry
    if not notes or all(n.startswith("kept") for n in notes):
        return notes or ["already up to date"]
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            backup = path.with_suffix(f".json.bak-{time.strftime('%Y%m%d-%H%M%S')}")
            shutil.copy2(path, backup)
            notes.append(f"backup: {backup.name}")
        path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return notes


def startup_script(python: str) -> str:
    pythonw = pathlib.Path(python).with_name("pythonw.exe")
    exe = str(pythonw) if pythonw.exists() else python
    return ("@echo off\r\n"
            "rem Starts the kazi-rhino voice server (hushtype -> Rhino). Delete this file to stop.\r\n"
            f'start "kazi voice" /min "{exe}" -m rhino_ai_mods.voice.server serve\r\n')


def claude_code_commands(python: str, uvx: str | None) -> list[list[str]]:
    cmds = [["claude", "mcp", "add", "--scope", "user", "rhino-ai-mods", "--",
             python, "-m", "rhino_ai_mods.mcp_server"]]
    if uvx:
        cmds.append(["claude", "mcp", "add", "--scope", "user", "rhino", "--", uvx, "rhinomcp@latest"])
    return cmds


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kazi-setup", description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-desktop", action="store_true", help="skip Claude Desktop config")
    ap.add_argument("--no-claude-code", action="store_true", help="skip Claude Code registration")
    ap.add_argument("--no-autostart", action="store_true", help="skip starting rhino-voice with Windows")
    ap.add_argument("--config", help="Claude Desktop config path (default: the standard location)")
    args = ap.parse_args(argv)

    python = sys.executable
    uvx = shutil.which("uvx")
    entries = server_entries(python, uvx)
    print(f"kazi-setup ({'dry run' if args.dry_run else 'applying'})  python={python}")
    if not uvx:
        print("! uv/uvx not found: rhinomcp won't be registered. Install uv: winget install astral-sh.uv")

    if not args.no_desktop:
        path = pathlib.Path(args.config) if args.config else desktop_config_path()
        for note in merge_desktop_config(path, entries, args.dry_run):
            print(f"Claude Desktop ({path}): {note}")

    if not args.no_claude_code:
        if shutil.which("claude"):
            for cmd in claude_code_commands(python, uvx):
                print("Claude Code:", " ".join(cmd[:6]))
                if not args.dry_run:
                    subprocess.run(cmd, check=False)
        else:
            print("Claude Code: `claude` not on PATH, skipped")

    sd = startup_dir()
    if not args.no_autostart and sd is not None:
        target = sd / "kazi-voice.cmd"
        print(f"Windows startup: {target}")
        if not args.dry_run:
            target.write_text(startup_script(python), encoding="utf-8")

    bridge = REPO / "bridge" / "install_in_rhino.py"
    print("\nLast step, in Rhino 8 (once):")
    print(f'  _-ScriptEditor _Run "{bridge}"')
    print('  then add  KaziStart  to Tools > Options > General > "Run these commands every time Rhino starts"')
    print("Restart Claude Desktop to load the new MCP servers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
