# kazi-rhino

My Rhino 8 setup, modded with AI:

1. **Claude drives Rhino** through [rhinomcp](https://github.com/jingcheng-chen/rhinomcp), the open-source Rhino MCP server (geometry, layers, commands, Grasshopper wiring and sliders).
2. **Claude writes Grasshopper scripts.** rhinomcp can't author script components, so this repo adds a small bridge + MCP server that lets Claude create Python 3 / C# script components with code, inputs and outputs, wire them up, and read back errors so it can fix its own code.
3. **Voice to the Rhino command line.** Speak, and it runs in Rhino. Text comes from [hushtype](https://github.com/armaan-k019/hushtype) (my Wispr Flow-style dictation app), gets mapped to a Rhino macro by fast rules or a Hugging Face model, and is typed into Rhino's command line.

```
                        ┌───────────────── Rhino 8 ──────────────────┐
Claude ──MCP── rhinomcp ─┼─ port 1999  (rhinomcp plugin, `mcpstart`) │
       └─MCP── rhino-ai-mcp ─┐                                      │
                             ├─ port 2010 (bridge/rhino_ai_bridge.py)│
mic → hushtype ─HTTP→ rhino-voice ─┘   Grasshopper script comps,     │
                  :8765                command line                  │
                        └───────────────────────────────────────────┘
```

## Quick start

Requirements: Rhino 8 (built for Windows; Mac should work), Python 3.10+, [uv](https://docs.astral.sh/uv/) recommended.

```bash
git clone https://github.com/armaan-k019/kazi-rhino && cd kazi-rhino
uv venv && uv pip install -e ".[hf]"      # or: pip install -e ".[hf]"
```

1. **rhinomcp** (base MCP): follow [docs/01-rhino-mcp.md](docs/01-rhino-mcp.md).
2. **Start the bridge in Rhino** (every session, or add it to startup, see the doc):
   `_-ScriptEditor _Run "C:\path\to\kazi-rhino\bridge\rhino_ai_bridge.py"`
3. **Grasshopper scripting for Claude**: [docs/02-grasshopper-scripts.md](docs/02-grasshopper-scripts.md).
4. **Voice**: [docs/03-voice-to-rhino.md](docs/03-voice-to-rhino.md). Short version:
   ```bash
   rhino-voice serve            # local Qwen2.5-1.5B via transformers
   rhino-voice --llm none serve # rules only, no model
   rhino-voice --dry-run say "make a box ten by ten by five"
   ```

## Repo layout

| Path | What |
| --- | --- |
| `bridge/rhino_ai_bridge.py` | Runs inside Rhino 8 (CPython). JSON-over-TCP server on 127.0.0.1:2010 |
| `src/rhino_ai_mods/mcp_server.py` | `rhino-ai-mcp`: MCP tools for Grasshopper script components |
| `src/rhino_ai_mods/voice/` | `rhino-voice`: dictation → rules / HF model → Rhino command line |
| `config/` | Example MCP configs for Claude Desktop and Claude Code |
| `tests/` | `pytest`, uses a fake bridge, no Rhino needed |

## Status

Built and unit-tested without Rhino (28 tests, plus an end-to-end run with hushtype against a fake bridge). The Rhino side has not been run in a real Rhino yet, so expect some first-run fixes. Run `bridge_status` and the smoke test in docs/02 first.
