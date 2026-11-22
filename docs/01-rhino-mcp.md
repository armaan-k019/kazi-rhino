# 1. Getting started with the Rhino MCP

MCP (Model Context Protocol) is how Claude gets "hands": an MCP server exposes tools (create a box, run a command, add a Grasshopper component), and Claude decides when to call them. For Rhino the server is split in two:

- a **Rhino plugin** that opens a local socket inside Rhino (`mcpstart`), and
- a **Python MCP server** (`uvx rhinomcp`) that Claude launches and that talks to that socket.

We use [jingcheng-chen/rhinomcp](https://github.com/jingcheng-chen/rhinomcp) as the base. It is MIT-licensed, maintained, installs from Rhino's Package Manager, and covers geometry, layers, selection, measuring, viewport capture, running any command, running RhinoScript-Python / RhinoCommon C#, and Grasshopper component placement, wiring, sliders and solving.

## Install (about 10 minutes)

1. **Rhino 8.20 or newer.** Check with `SystemInfo`. On Windows it must say .NET 8 (if not, run `SetDotNetRuntime`, choose `NETCore`, restart).
2. **Rhino plugin:** Tools → Package Manager → search `rhinomcp` → Install → restart Rhino.
3. **uv** (runs the Python server): `winget install astral-sh.uv` (Windows) or `brew install uv` (Mac).
4. **Connect Claude.**
   - Claude Code: `claude mcp add rhino -- uvx rhinomcp@latest`
   - Claude Desktop: Settings → Developer → Edit Config, and merge in [config/claude_desktop_config.json](../config/claude_desktop_config.json). Restart Claude Desktop.
5. **Start the bridge in Rhino:** type `mcpstart` (once per Rhino session). `mcpstatus` shows the port (1999 by default).

To have Rhino start everything automatically, add this to Tools → Options → General → "Run these commands every time Rhino starts":

```
_mcpstart
_-ScriptEditor _Run "C:\path\to\rhino-ai-mods\bridge\rhino_ai_bridge.py"
```

## Learn it by doing

Ask Claude these in order. Each one teaches you a capability and how Claude thinks about Rhino.

1. "What's in my Rhino document right now?" (document summary, layers)
2. "Make a 10 x 10 x 3 box at the origin, then a sphere of radius 4 centred on its top face." (create objects)
3. "Boolean-difference the sphere out of the box and tell me the volume." (boolean + analysis)
4. "Capture the viewport and describe what you see." (visual feedback loop)
5. "Make a layer called facade, put a 30 x 10 wall on it, and divide it into 12 vertical panels." (layers + scripting)
6. "Run the Make2D command on everything from the front view." (any Rhino command)
7. "Open Grasshopper and build: a number slider 1–20 → Divide Curve on a circle of radius 10 → points." (GH wiring)
8. "Now add a Python script that moves each point up by a sine wave." (this needs our add-on, see [02-grasshopper-scripts.md](02-grasshopper-scripts.md))

Tips:
- Say *which* tool family you want when it matters: "use RhinoScript Python" vs "use Grasshopper".
- Ask Claude to **capture the viewport** after big steps. It catches its own mistakes much faster.
- Rhino's Undo works on everything Claude does.
- Claude can only see Rhino while `mcpstart` is running.

## How it fits with this repo

| Need | Use |
| --- | --- |
| Model geometry, run commands, wire normal GH components, sliders | rhinomcp (`rhino` server) |
| Create / edit Python or C# script components, read their code and errors | rhino-ai-mods (`rhino-ai-mods` server) |
| Speak commands | `rhino-voice` |

Both MCP servers can be connected at the same time. Our bridge uses port 2010, outside rhinomcp's 1999–2008 range, so they don't clash.
