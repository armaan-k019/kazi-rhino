# 3. Voice to the Rhino command line

Speak; Rhino does it. The pipeline:

```
hushtype (mic → faster-whisper → clean text)
   │ POST http://127.0.0.1:8765/dictation  {"text", "app", "source", "mode"}
   ▼
rhino-voice
   1. rules     "undo", "zoom extents", "boolean union", "circle 0,0,0 5"  → instant, no model
   2. HF model  "make a box ten by ten by five" → _Box 0,0,0 10,10,0 5
   3. check     the command must exist in your Rhino (live list from the bridge)
   ▼
bridge → types the macro into Rhino's command line
```

## Run it

```bash
uv pip install -e ".[hf]"          # transformers + torch for the local model
rhino-voice serve                   # default model: Qwen/Qwen2.5-1.5B-Instruct (local)
```

Other options:

```bash
rhino-voice --model Qwen/Qwen2.5-3B-Instruct serve   # bigger = smarter, slower
rhino-voice --llm hf-api serve                       # Hugging Face Inference (needs HF_TOKEN, pip install -e ".[hf-api]")
rhino-voice --llm none serve                         # rules only
rhino-voice --dry-run say "copy these twenty to the right"   # see the macro, don't run it
rhino-voice repl                                      # type phrases to test
```

Any Hugging Face chat/instruct model works with `--model`. Good choices: `Qwen/Qwen2.5-1.5B-Instruct` (CPU-friendly), `Qwen/Qwen2.5-7B-Instruct` (GPU or `hf-api`), `meta-llama/Llama-3.2-3B-Instruct`, `microsoft/Phi-3.5-mini-instruct`.

## With hushtype

hushtype already speaks this contract. Two ways in:

- **Send-to-Rhino hotkey** (default `ctrl+alt+r`, `mode: "rhino"`): always treated as a command. If nothing matches, the words are typed into Rhino's command line *without* Enter, so Rhino's own autocomplete acts like a search bar.
- **Normal dictation while Rhino is focused** (`mode: "dictate"`): only clear commands run; anything else gets a 409 and hushtype pastes the text normally (so you can still dictate into a Text object or a Panel). The model is not used in this mode unless you pass `--llm-in-dictate`, because hushtype only waits 2 seconds.

## Safety

- Destructive commands (Delete, Exit, Close, New, Open, Purge, Import, ...) are typed but **not** confirmed; press Enter yourself.
- `--no-enter` makes every command wait for your Enter.
- Model output is rejected unless its command exists in your Rhino.
- Everything runs on localhost; nothing leaves your machine with `hf-local`.

## Adding your own phrases

Edit `ALIASES` in [src/rhino_ai_mods/voice/rules.py](../src/rhino_ai_mods/voice/rules.py):

```python
"section cut": "_ClippingPlane",
"make it pretty": "_-SetDisplayMode _Mode=Arctic",
```

Plugin commands (Ladybug, Elefront, your own) are picked up automatically from Rhino's live command list, so "elefront bake" works once the plugin is loaded.
