import json

from rhino_ai_mods import setup_cli


def test_merge_into_existing_config_keeps_everything(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text(json.dumps({"theme": "dark", "mcpServers": {"notion": {"command": "x"},
                                                              "rhino": {"command": "mine"}}}))
    entries = setup_cli.server_entries("C:/kazi/.venv/Scripts/python.exe", "C:/uv/uvx.exe")
    notes = setup_cli.merge_desktop_config(cfg, entries)
    data = json.loads(cfg.read_text())
    assert data["theme"] == "dark" and data["mcpServers"]["notion"] == {"command": "x"}
    assert data["mcpServers"]["rhino"] == {"command": "mine"}  # user's own rhino entry kept
    assert data["mcpServers"]["rhino-ai-mods"]["args"] == ["-m", "rhino_ai_mods.mcp_server"]
    assert any(n.startswith("backup") for n in notes)
    assert len(list(tmp_path.glob("*.bak-*"))) == 1
    # second run: nothing to do, no new backup
    assert setup_cli.merge_desktop_config(cfg, entries) == ["kept your existing 'rhino' server"]
    assert len(list(tmp_path.glob("*.bak-*"))) == 1


def test_new_config_and_dry_run(tmp_path):
    cfg = tmp_path / "Claude" / "claude_desktop_config.json"
    entries = setup_cli.server_entries("py", None)
    assert setup_cli.merge_desktop_config(cfg, entries, dry_run=True) == ["added 'rhino-ai-mods'"]
    assert not cfg.exists()
    setup_cli.merge_desktop_config(cfg, entries)
    assert json.loads(cfg.read_text()) == {"mcpServers": {"rhino-ai-mods": {
        "command": "py", "args": ["-m", "rhino_ai_mods.mcp_server"]}}}


def test_startup_script_and_claude_code_commands():
    s = setup_cli.startup_script("C:/kazi/.venv/Scripts/python.exe")
    assert "rhino_ai_mods.voice.server serve" in s and s.endswith("\r\n") and "/min" in s
    cmds = setup_cli.claude_code_commands("py", "uvx")
    assert cmds[0][:6] == ["claude", "mcp", "add", "--scope", "user", "rhino-ai-mods"]
    assert cmds[1][-1] == "rhinomcp@latest"


def test_cli_dry_run_prints_rhino_step(tmp_path, capsys):
    assert setup_cli.main(["--dry-run", "--config", str(tmp_path / "c.json"), "--no-claude-code"]) == 0
    out = capsys.readouterr().out
    assert "install_in_rhino.py" in out and "KaziStart" in out
    assert not (tmp_path / "c.json").exists()
