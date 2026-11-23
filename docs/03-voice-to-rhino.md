# 3. Voice for Rhino and Grasshopper

Hold a key, speak, let go. hushtype turns speech into text, and rhino-voice decides what to do with it:

```
hold Ctrl+Alt+R  → Rhino command        "sel prev" / "select previous"  → _SelPrev typed, waits for Enter
hold Ctrl+Alt+G  → Grasshopper build    "build me a voronoi script that attaches to the facade"
                                         → Yes/No dialog in Rhino → sliders + script wired on the canvas
hold Ctrl+Alt+Space while Rhino is focused → only exact command names run, everything else is pasted
```

The mic is only open while one of these keys is held. Nothing listens in the background.

## Nothing runs without you

- **Rhino commands** are typed into the command line and wait. Press **Enter** to run, **Esc** to cancel.
  Start with `--auto-run` if you'd rather have safe commands run immediately (Delete, Exit, Open,
  Purge and similar still always wait).
- **Grasshopper builds** show a dialog with what will be built (inputs, slider ranges, which
  selected objects are used). Click **No** and nothing is added.

## Rhino: say commands the way you talk

```
"sel prev", "select previous", "SelPrev", "sell prev"   → _SelPrev
"select by layer"                                         → _SelLayer
"extrude curve", "planar surface", "sweep two"            → _ExtrudeCrv, _PlanarSrf, _Sweep2
"duplicate edge", "points on", "make 2d"                  → _DupEdge, _PointsOn, _Make2D
"circle zero comma zero comma zero five"                  → _Circle 0,0,0 5
"bullion union"                                           → _BooleanUnion   (common mishearing)
"make a box ten by ten by five"                           → model → _Box 0,0,0 10,10,0 5
```

How: spoken words are turned into Rhino's abbreviations (select→Sel, previous→Prev, curve→Crv,
surface→Srf, point→Pt, duplicate→Dup, ...), filler words are dropped ("by", "the", "please"), and
the result is matched against the **live command list from your Rhino**, so plugin commands work
too. If that fails, a close-spelling match is tried (only on the Rhino hotkey), then the model.

Your own phrases go in `~/.kazi-rhino/aliases.json` (see [config/aliases.example.json](../config/aliases.example.json)):

```json
{ "section cut": "_ClippingPlane", "make it pretty": "_-SetDisplayMode _Mode=Arctic" }
```

## Grasshopper: describe it, get a working definition

```
"build me a voronoi script that attaches to a facade with 80 cells"
"build a stepping condition that sets back 3 metres every 4 floors, 20 floors"
"make a grasshopper definition for vertical fins along this curve"     (needs a model)
```

What gets built: a **Geometry** input holding what you have selected in Rhino (live-referenced,
so editing the Rhino object updates Grasshopper), a **slider** or **toggle** for every parameter,
one **Python 3 script** with the logic, all wired, grouped and named, then solved. If the script
errors and a model is configured, the error goes back to the model to fix (up to 2 times).
The Rhino command line reports what happened (`[kazi] built 'Voronoi facade'`).

Built-in recipes (tested, work with no model at all):

| Recipe | Say | Inputs |
| --- | --- | --- |
| Voronoi facade | "voronoi", "cellular" | facade (selection), count, seed, frame → cells, openings, sites |
| Stepped massing | "stepping", "setback", "terraced", "tiered" | footprint (selection), floors, floor height, floors per tier, setback → masses, slabs, terraces |

Numbers you say become slider values ("80 cells", "20 floors", "every 4 floors", "setback of 3").

For anything else, a model writes the script. Writing good Grasshopper code needs a stronger
model than your laptop's CPU can run quickly, so pick one:

```powershell
$env:ANTHROPIC_API_KEY = "..."; rhino-voice serve   # Claude (best). pip install -e ".[anthropic]"
$env:HF_TOKEN = "...";          rhino-voice serve   # Qwen2.5-Coder-32B on Hugging Face. pip install -e ".[hf-api]"
rhino-voice --gh-llm none serve                     # recipes only
```

With a model, recipe requests still start from the tested recipe, and the model only changes
what you asked for beyond it ("...with bigger openings near the top").

## Run it

```bash
uv pip install -e ".[hf]"           # local command model (Qwen2.5-1.5B, CPU is fine)
rhino-voice serve                    # listens on http://127.0.0.1:8765/dictation
```

```bash
rhino-voice --dry-run say "select previous"          # show the macro, don't send it
rhino-voice gh "build a terraced massing, 12 floors" # build from the terminal (Rhino + bridge running)
rhino-voice repl                                      # type phrases to test
rhino-voice --model Qwen/Qwen2.5-0.5B-Instruct serve # faster command model
rhino-voice --auto-run serve                          # safe commands run without Enter
rhino-voice --no-confirm-builds serve                 # skip the Grasshopper dialog
```

## Speed on a CPU-only laptop

| Model | Time per sentence (CPU) | Notes |
| --- | --- | --- |
| rules (most commands) | instant | no model involved |
| `Qwen/Qwen2.5-1.5B-Instruct` (default) | about 4 s on a 4-core CPU | your laptop should be faster |
| `Qwen/Qwen2.5-0.5B-Instruct` | about 1.5–2 s | more mistakes on long sentences |
| Grasshopper scripts via Claude / HF API | roughly 10–40 s (estimate, not measured) | runs remotely; recipes are instant |

## HTTP contract (for hushtype or anything else)

`POST /dictation` with `{"text", "app", "source", "mode": "rhino" | "grasshopper" | "dictate"}`.
`200` handled · `202` accepted, working in the background (Grasshopper builds, model lookups) ·
`409` not a command, paste it · `503` Rhino or the bridge isn't running, paste it.
