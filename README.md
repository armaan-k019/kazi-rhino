# kazi-rhino

My Rhino 8 setup, modded with AI:

1. **Claude drives Rhino** through [rhinomcp](https://github.com/jingcheng-chen/rhinomcp), the open-source Rhino MCP server (geometry, layers, commands, Grasshopper wiring and sliders).
2. **Claude writes Grasshopper scripts.** rhinomcp can't author script components, so this repo adds a small bridge + MCP server that lets Claude create Python 3 / C# script components with code, inputs and outputs, wire them up, and read back errors so it can fix its own code.
3. **Voice to the Rhino command line.** Speak, and it runs in Rhino. Text comes from [hushtype](https://github.com/armaan-k019/hushtype) (my Wispr Flow-style dictation app), gets mapped to a Rhino macro by fast rules or a Hugging Face model, and is typed into Rhino's command line.
4. **Free Grasshopper add-ons by voice or through Claude.** "Panelize this facade with LunchBox", "Ladybug sun hours study", "relax this mesh with Kangaroo": components from LunchBox, Ladybug Tools, Kangaroo 2, Weaverbird, Pufferfish, Elefront, Human, Wallacei, Hops and Speckle are placed and wired for you. [Install guide and phrases](docs/04-grasshopper-addons.md).

```
                        ┌───────────────── Rhino 8 ──────────────────┐
Claude ──MCP── rhinomcp ─┼─ port 1999  (rhinomcp plugin, `mcpstart`) │
       └─MCP── rhino-ai-mcp ─┐                                      │
                             ├─ port 2010 (bridge/rhino_ai_bridge.py)│
mic → hushtype ─HTTP→ rhino-voice ─┘   Grasshopper script comps,     │
                  :8765                command line                  │
                        └───────────────────────────────────────────┘
```

## Quick start (Windows)

Requirements: Rhino 8, the rhinomcp plugin (Package Manager, search "rhinomcp"), Python 3.10+.

```powershell
git clone https://github.com/armaan-k019/kazi-rhino; cd kazi-rhino
powershell -ExecutionPolicy Bypass -File .\install.ps1        # add -Extras "hf,anthropic" for Claude-written scripts
```

`install.ps1` installs uv if needed, makes `.venv`, installs the package and runs `kazi-setup`, which:
adds both MCP servers to Claude Desktop (keeps your other servers, saves a backup), registers them
with Claude Code if it's installed, and starts `rhino-voice` with Windows (`-NoAutostart` to skip).
Then, once in Rhino:

```
_-ScriptEditor _Run "C:\path\to\kazi-rhino\bridge\install_in_rhino.py"
```

That adds these Rhino commands (add `KaziStart` to Tools > Options > General > startup commands):

| Command | Does |
| --- | --- |
| `KaziStart` | Starts rhinomcp (`mcpstart`) and the kazi bridge |
| `KaziStop` | Stops the bridge |
| `KaziStatus` | Bridge version, port, last builds |
| `KaziUndoBuild` | Removes the last voice/Claude-built Grasshopper definition |
| `KaziBake` | Bakes the last build's outputs to layers `kazi::<build>::<output>` (one undo step) |

Docs: [rhinomcp](docs/01-rhino-mcp.md) · [Grasshopper scripts](docs/02-grasshopper-scripts.md) ·
[voice](docs/03-voice-to-rhino.md) ·
[add-ons](docs/04-grasshopper-addons.md). Hold Ctrl+Alt+R for commands ("select previous"), Ctrl+Alt+G
for Grasshopper ("build a voronoi script on the facade", then "more cells", "thinner frame", "bake it").
Nothing runs until you confirm. Recipes: voronoi facade, attractor openings, fins/louvres, panels,
diagrid, stepped massing; anything else is written by a model.

```bash
rhino-voice --dry-run say "make a box ten by ten by five"   # try the mapping without Rhino
```

## Repo layout

| Path | What |
| --- | --- |
| `bridge/rhino_ai_bridge.py` | Runs inside Rhino 8 (CPython). JSON-over-TCP server on 127.0.0.1:2010 |
| `src/rhino_ai_mods/mcp_server.py` | `rhino-ai-mcp`: MCP tools for Grasshopper script components |
| `src/rhino_ai_mods/voice/` | `rhino-voice`: dictation → rules / HF model → Rhino command line |
| `bridge/kazi_addons.py`, `src/rhino_ai_mods/addons/` | Grasshopper add-ons: component search, placing, wiring, ready-made definitions, `kazi-addons check` |
| `bridge/install_in_rhino.py`, `bridge/kazi_*.py` | The Kazi* Rhino commands |
| `src/rhino_ai_mods/setup_cli.py`, `install.ps1` | One-step setup |
| `config/` | Example MCP configs for Claude Desktop and Claude Code |
| `tests/` | `pytest`, uses a fake bridge, no Rhino needed |

## Testing

```bash
uv pip install -e ".[dev,anthropic]"
pytest                                  # ~190 tests, no Rhino needed, ~25 s
python tools/check_rhino_api.py         # every RhinoCommon/Grasshopper call vs the real Rhino 8 assemblies
```

What the tests cover without Rhino:
- **Recipes run** in a simulated RhinoCommon (real polygon/offset math): voronoi cells tile the facade
  exactly, stepped massing produces the right tiers, slabs, setbacks and terraces.
- **The bridge script itself** (`bridge/rhino_ai_bridge.py`) runs against fake Rhino/Grasshopper
  objects: UI-thread marshalling, command typing, script params (including Rhino 8's `out`), sliders,
  wiring, groups, selection references, dialogs.
- **End to end**: dictation HTTP → `rhino-voice` → bridge, and Claude → MCP → `rhino-ai-mcp` → bridge.
- **API check**: 210 member/overload uses verified against RhinoCommon + Grasshopper 8.36 from NuGet.

What still needs a real Rhino: the actual geometry results in RhinoCommon, and Rhino 8 script
component internals (`SetSource`, marshalling flags), which aren't in the public assemblies.

## Status

Unit and simulation tested (see above). Not yet run inside a real Rhino: do the smoke test in
docs/02 first and send any errors back.
