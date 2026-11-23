# 2. Claude in Grasshopper: script components

The `rhino-ai-mods` MCP server lets Claude write Grasshopper script components: it places a Python 3 (or C# / IronPython) script component, sets its inputs, outputs and code, solves it, and reads back the errors so it can fix the script itself.

## Setup

1. In Rhino, run `KaziStart` (after the one-time `install_in_rhino.py`, see the README), or start the bridge directly:
   `_-ScriptEditor _Run "C:\path\to\kazi-rhino\bridge\rhino_ai_bridge.py"`
   You should see `rhino-ai-mods bridge 0.3.0 listening on 127.0.0.1:2010`. Run it again to restart; `bridge/stop_bridge.py` stops it.
2. Open Grasshopper (the bridge will also try to open it when needed).
3. Connect the MCP server to Claude:
   - Claude Code (from the repo folder): `claude mcp add rhino-ai-mods -- uv run --directory C:/path/to/kazi-rhino rhino-ai-mcp`
   - Claude Desktop: see [config/claude_desktop_config.json](../config/claude_desktop_config.json).
4. Ask Claude: "Check the rhino-ai-mods bridge status."

## Tools

| Tool | Does |
| --- | --- |
| `bridge_status` | Rhino version, open document, whether Grasshopper is open |
| `gh_create_script` | New script component: `code`, `language` (python / csharp / ironpython), `inputs`, `outputs`, position. Returns errors from the first solve |
| `gh_update_script` | Change code and/or params of an existing script, re-solve, return errors |
| `gh_read_script` | Code + params + output data preview + messages |
| `gh_list` | Everything on the canvas, with wires and messages |
| `gh_add_component` | Any component by name ("Number Slider", "Panel", "Loft", ...) |
| `gh_connect` / `gh_disconnect` | Wire output → input (by nickname, name or index) |
| `gh_delete`, `gh_solve` | Delete a component; recompute everything and list problems |
| `gh_build` | **One call, whole definition**: geometry from the Rhino selection + sliders/toggles → one script → outputs, wired, grouped, solved, errors returned. Or `recipe="voronoi_facade"` |
| `gh_recipes` | Tested plans (voronoi facade, stepped massing) to build or adapt |
| `gh_add_slider`, `gh_add_geometry_input` | A slider with range/value; a Geometry param referencing the Rhino selection |
| `rhino_selection` | What's selected in Rhino |
| `voice_command` | How a spoken phrase maps to a command ("select previous" → `_SelPrev`); `run=true` types it |
| `rhino_run_macro` | Run a Rhino command macro |

Inputs can be plain names (`["pts", "h"]`) or dicts: `{"name": "pts", "access": "list", "optional": true}`.

## How this fits with rhinomcp

Use both servers together; Claude picks the right tool. rhinomcp models geometry, reads the
document, captures the viewport and drives normal Grasshopper components. rhino-ai-mods writes
scripts and builds whole slider-driven definitions (`gh_build`). A good loop:

> Select the facade. "Using gh_build, make a parametric fin system on the selected facade with
> count, depth and rotation sliders. Then capture the viewport with rhinomcp and fix anything that
> looks wrong."

## Smoke test (do this first)

Ask Claude:

> Using rhino-ai-mods: create a Python script component called `wave` with inputs `n` (item) and `amp` (item) and output `pts`. Code: make `n` points along X spaced 1 apart, with Z = amp·sin(x). Add two number sliders and wire them into n and amp, then read the script back and tell me how many points it produced.

What to check on the canvas: one component named `wave` with inputs `n`, `amp` and output `pts`, two sliders wired in, and points in the Rhino viewport.

## Known first-run risks

This was built and tested without a live Rhino, against the Rhino 8 Grasshopper API. The parts most likely to need a fix on first run:

- **Adding/renaming params** on Rhino 8 script components (`_set_params` in the bridge). If inputs don't change, tell Claude to report the error from `gh_create_script`; the fallback is to create it without `inputs` and rename the default `x`/`y`.
- **Marshalling flags.** Rhino 8's `SetSource` resets input/output marshalling, which turns geometry outputs into strings. The bridge saves and restores them. If outputs show up as text like `<Rhino.Geometry.Point3d ...>`, that's the cause.
- **Running a command while another is active.** `rhino_run_macro` with `wait=True` blocks until the command finishes; use the default (typed) mode for interactive commands.

## Example prompts

- "Make a C# script that takes a list of curves and outputs their total length."
- "Read the script `wave` and refactor it to output a NURBS curve through the points instead."
- "Build a parametric louvre facade: a surface input, a count slider, a depth slider, and a Python script that generates fins. Fix any errors until it solves cleanly."
