# Grasshopper add-ons: install guide and how to use them by voice or through Claude

kazi can place and wire components from ten free add-ons. Say or type what you want, confirm
the dialog in Rhino, and the definition is built, grouped and solved:

> "Panelize this facade with LunchBox, ten by twenty."

Nothing here needs an NVIDIA GPU. Everything goes through the same Rhino bridge and MCP server
as the rest of kazi, so `KaziUndoBuild` and `KaziBake` work on add-on builds too.

## 1. Install the add-ons (Windows, Rhino 8)

Most of them install from inside Rhino:

1. In Rhino, type `PackageManager` and press Enter.
2. Search for the name in the table, select it, click **Install**.
3. Restart Rhino when you have installed everything.

| Add-on | What it is for | How to install | Cost |
| --- | --- | --- | --- |
| **Kangaroo 2** | Physics: form-finding, tensile and hanging shapes | Already in Rhino 8. Nothing to do | Free |
| **LunchBox** | Panels, diagrids, space trusses, Excel, bake tools | `PackageManager` > "LunchBox" | Free |
| **Weaverbird** | Mesh subdivision, frames, windows, thickening | `PackageManager` > "Weaverbird" | Free |
| **Pufferfish** | Tweens, blends, morphs, offsets | `PackageManager` > "Pufferfish" | Free |
| **Human** | Layers, attributes, views from Grasshopper | `PackageManager` > "Human" | Free |
| **Elefront** | Baking with layers, names, user attributes | `PackageManager` > "Elefront" (see note 1) | Free |
| **Wallacei** | Evolutionary optimisation | `PackageManager` > "Wallacei" (see note 1) | Free |
| **Hops** | Run a Grasshopper file or Python function as a component | `PackageManager` > "Hops" | Free |
| **Ladybug Tools** | Sun path, sun hours, radiation, wind, energy, daylight | Its own installer (section 1.1) | Free, open source |
| **Speckle** | Send models between Rhino, Revit, Blender, the web | Its own installer (section 1.2) | Free plan |

Note 1: I confirmed LunchBox, Weaverbird, Human and Pufferfish are in the Package Manager. I
could not confirm Elefront and Wallacei from here. If one is not listed, use the manual route:

1. Download the zip from Food4Rhino ([Elefront](https://www.food4rhino.com/en/app/elefront),
   [Wallacei](https://www.food4rhino.com/en/app/wallacei)). A free Food4Rhino account is needed.
2. Right-click the zip > Properties > tick **Unblock** > OK. Then unzip it.
3. In Grasshopper: File > Special Folders > Components Folder. Copy the `.gha` (and any `.dll`)
   files there.
4. Restart Rhino.

Wallacei's Food4Rhino page says it is designed for Rhino 6 and 7. It is widely used in Rhino 8,
but if it fails to load, that is why.

Prefer the command line? The package manager's tool is `yak.exe` in Rhino's `System` folder
(McNeel documents `C:\Program Files\Rhino 9\System\Yak.exe` for Rhino 9; Rhino 8 uses the
`Rhino 8` folder). Check the file exists, then:

```powershell
& "C:\Program Files\Rhino 8\System\Yak.exe" search lunchbox
& "C:\Program Files\Rhino 8\System\Yak.exe" install lunchbox
```

### 1.1 Ladybug Tools

Ladybug is not in the Package Manager.

1. Download the Ladybug Tools zip from [Food4Rhino](https://www.food4rhino.com/en/app/ladybug-tools).
2. Right-click the zip > Properties > **Unblock**, then unzip it.
3. Open Rhino 8 and Grasshopper. Drag the `installer.gh` file from the unzipped folder onto the
   Grasshopper canvas. Stay online.
4. Double-click the first toggle to set it to True and wait about a minute. Then the second
   toggle, and wait until it reports it is done.
5. Restart Rhino. The Ladybug, Honeybee, HB-Radiance, HB-Energy and Dragonfly tabs appear.

Sun path, sun hours, radiation and wind rose work straight away. Honeybee daylight and energy
simulations also need the free Radiance and OpenStudio programs; the Ladybug Tools wiki on
GitHub lists the versions that match.

Weather files: Ladybug needs an `.epw` file for your site. Open
[ladybug.tools/epwmap](https://www.ladybug.tools/epwmap/), click your city and copy the link to
its zip file. kazi's Ladybug builds include a panel to paste that link into.

### 1.2 Speckle

1. Make a free account at [app.speckle.systems](https://app.speckle.systems).
2. Download the Rhino / Grasshopper connector from
   [app.speckle.systems/connectors](https://app.speckle.systems/connectors) and run the installer.
3. Restart Rhino. A Speckle tab appears in Grasshopper. Sign in with the Sign-In component.

### 1.3 Check what kazi can see

Start Rhino, run `KaziStart`, open Grasshopper, then in a terminal:

```powershell
kazi-addons check
```

This lists which add-ons are installed, tells you how to install the missing ones, and tests
every ready-made definition against the components really on your machine, without touching
the canvas. If an add-on renamed a component or an input in your version, it shows up here as
a PROBLEM line. The full report is saved to `~/.kazi-rhino/addons_audit.json`. Claude can run
the same check with the `gh_addons` tool.

**Run this once after installing.** The component names in this repo come from each add-on's
documentation and source code, not from a live Rhino, so this check is the first real test.

## 2. Use them by voice

Hold the Grasshopper key (Ctrl+Alt+G in hushtype) and speak. Naming the add-on also works on
the Rhino key (Ctrl+Alt+R). You always get a Yes/No dialog first that lists the components and
sliders it will make. Select the geometry in Rhino before you speak.

| Say | You get |
| --- | --- |
| "Panelize this facade with LunchBox, ten by twenty" | Quad Panels with u and v sliders |
| "LunchBox diamond panels" / "hexagons" / "triangles" / "staggered" / "random quads" | That panel type |
| "LunchBox quads with frames" | Panels, then Panel Frame with a frame slider |
| "LunchBox diagrid twelve by eight" / "space truss depth one point five" | Structure lines and nodes |
| "Subdivide this mesh with Weaverbird, level two" | Catmull-Clark subdivision |
| "Weaverbird picture frame and thicken it" | Picture Frame, then Mesh Thicken |
| "Relax this mesh with Kangaroo" | Tensile relaxation with pinned edges |
| "Make a hanging shell with Kangaroo" | Hanging form under load |
| "Tween these curves with Pufferfish, twelve steps" | Tween Through Curves |
| "Pufferfish offset surface by zero point three" | Offset Surface as a solid |
| "Bake this with Elefront to layer facade panels" | Attributes + Bake Objects with a bake toggle |
| "Elefront reference everything from layer site" | Reference by Layer |
| "List my layers with Human" | Layer Table |
| "Create layers called glass and mullions with Human" | Create/Modify Layers |
| "Ladybug sun path" | Weather import + sun path |
| "Run a sun hours study on this" | Direct Sun Hours for 21 June, with a run toggle |
| "Solar radiation study on the facade" | Sky matrix + Incident Radiation, with a run toggle |
| "Show me a wind rose" | Wind rose |
| "Optimize this with Wallacei" | Wallacei X wired to the sliders of the last thing kazi built |
| "Add a Hops component" | Hops, ready for a path |
| "Publish this to Speckle" / "Load my Speckle model" | Model, collection and Publish / Load |

Things to know:

- **Heavy studies never start by themselves.** Ladybug studies and Elefront bakes are built with
  their run / bake toggle set to False. Flip it when you are ready.
- **Surfaces.** LunchBox and Pufferfish get the biggest face of whatever you selected, so a
  polysurface or extrusion works. Weaverbird and Kangaroo get a mesh made from your selection,
  with a "mesh edge" slider for its density.
- **Naming another component** places it: "add the LunchBox unroll brep component". With a model
  configured (`--gh-llm`), kazi asks the model to wire it up, and only accepts answers that use
  real component names.
- **If an add-on is missing**, nothing is added to the canvas and Rhino's command line tells you
  how to install it.
- **Wallacei always minimises.** The build includes a small "objectives" script with two example
  measures; edit it so each output is a number you want smaller.
- **Speckle** Publish and Load run when you click the button on the component.
- `kazi-addons list` prints these phrases. `kazi-addons build "..."` does the same from a terminal.

## 3. Use them through Claude (MCP)

The `rhino-ai-mcp` server gains these tools:

| Tool | Does |
| --- | --- |
| `gh_addons` | Which add-ons are installed, how to install the rest, what to ask for. `check_recipes=true` runs the full check |
| `gh_find_component` | Search any installed plug-in by words; returns exact names, inputs, outputs |
| `gh_place_component` | Place a component from a named add-on, optionally typing values into inputs |
| `gh_wire` | Wire two components; forgiving about parameter names; can flatten or graft |
| `gh_set_input` | Type a number, true/false, text or a list into an input |
| `gh_add_panel`, `gh_add_toggle` | Text panels and toggles |
| `gh_inspect` | One component in full: wires, data preview, errors |
| `gh_addon_build` | Build a ready-made definition from a sentence, like the voice command |
| `gh_build_graph` | Build a whole multi-component definition in one call (`check_only` to test first) |
| `gh_hops_set_path` | Point a Hops component at a `.gh` file or web address |
| `gh_learn_components` | Save every installed component to `~/.kazi-rhino/components.json` |

These work with **any** installed plug-in, not just the ten above: components are looked up in
Grasshopper's own list at run time.

## 4. Hops with Hugging Face models

`examples/hops_hf_server.py` is a small Python server that turns Hugging Face models into
Grasshopper components through Hops: `/ask` (prompt in, text out) and `/rank` (orders option
descriptions by how well they fit a brief). Both call Hugging Face's hosted models, so they need
a free `HF_TOKEN` and no GPU.

```powershell
pip install ghhops-server flask huggingface_hub
$env:HF_TOKEN = "hf_..."
python examples\hops_hf_server.py
```

Then say "add a hops component for http://127.0.0.1:5000/ask". I checked that the server starts
and describes its components to Hops; the model calls themselves were not run here.

## 5. What about Raven?

[Raven](https://www.raven.build) is a different kind of add-on. It is not a set of components
to place and wire: it is a chat assistant inside Grasshopper that writes, adjusts and repairs
definitions from plain language, which is the same job kazi does. So there is nothing for kazi
to drive, and it has no public way for another program to call it.

You can install it next to kazi and use both; they don't conflict. What I found (from
third-party listings in 2026, so check raven.build before relying on it):

- Rhino 8, installed from Rhino's `PackageManager` (search "Raven"), needs a Raven account.
- A free plan with a small monthly allowance (listed as 300 tokens), then paid plans from
  about $49 a month.
- It runs in Raven's cloud. On the free and Personal plans your prompts and context are used
  to improve their service; opting out needs the Professional plan.

Differences that matter here: kazi is voice-first with push-to-talk, uses models you choose
(Claude or Hugging Face), keeps a confirm step, and is yours to change. Raven is a polished
chat window that already knows many plug-ins.

## 6. How it works

| Piece | Where |
| --- | --- |
| Bridge commands that find, place and wire plug-in components | `bridge/kazi_addons.py` (loaded by `rhino_ai_bridge.py`) |
| Reference lists of about 1,300 components | `src/rhino_ai_mods/addons/data/*.json` |
| Names, spoken forms and install info for each add-on | `addons/registry.py` |
| Ready-made definitions | `addons/recipes.py` |
| Build plan and builder (confirm, check, place, wire, group, solve) | `addons/graph.py` |
| Voice / planner hook | `addons/planner.py` |
| Check and snapshot | `addons/audit.py`, `kazi-addons` |
| MCP tools | `addons/mcp_tools.py` |

To add a recipe: write a function in `addons/recipes.py` that returns a `GraphPlan`, give each
wire a few candidate parameter names, add a phrase to `EXAMPLES`, and run `pytest`. The tests
build every example against a simulated Grasshopper that has the catalogued components.

Where the reference lists came from: Ladybug Tools from its published component source code;
the others from their documentation pages. Pufferfish has 320 components and only the common
ones have their inputs listed; Speckle's nicknames were not documented. `kazi-addons check`
and `gh_find_component` read the truth from your own Grasshopper.
