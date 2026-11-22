"""Hugging Face model backends that turn free-form speech into a Rhino macro.

Two backends, both using any chat/instruct model on the Hugging Face Hub:

* ``hf-local``  runs the model on your machine with ``transformers`` (default
  Qwen/Qwen2.5-1.5B-Instruct; works on CPU, fast on a GPU).
* ``hf-api``    calls Hugging Face Inference Providers with ``huggingface_hub``
  (needs HF_TOKEN; default Qwen/Qwen2.5-7B-Instruct).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Protocol

SYSTEM_PROMPT = """\
You turn a spoken request from an architect using Rhino 8 into ONE Rhino command-line macro.

Rules:
- Reply with JSON only: {"macro": "<macro>", "is_command": true}
  or {"macro": "", "is_command": false} if the speech is not a request to do something in Rhino.
- Start every command name with an underscore (_Box, _Circle). Options as _Name=Value.
- Use real Rhino 8 command names only. Prefer simple commands over scripts.
- Coordinates are x,y,z with no spaces. Lengths are in model units. "Origin" is 0,0,0.
- If the request needs the user to pick objects or points that were not given, end the macro
  where Rhino would prompt, so Rhino asks the user (e.g. "_Move" or "_Loft").
- Commands act on the current selection when the user says "this", "these", "selected".

Examples:
"make a box ten by ten by five" -> {"macro": "_Box 0,0,0 10,10,0 5", "is_command": true}
"draw a circle radius 5 at the origin" -> {"macro": "_Circle 0,0,0 5", "is_command": true}
"sphere at 10,0,0 with radius 3" -> {"macro": "_Sphere 10,0,0 3", "is_command": true}
"move this up 10" -> {"macro": "_Move 0,0,0 0,0,10", "is_command": true}
"copy these 20 to the right" -> {"macro": "_Copy 0,0,0 20,0,0 _Enter", "is_command": true}
"loft the selected curves" -> {"macro": "_Loft", "is_command": true}
"fillet edges" -> {"macro": "_FilletEdge", "is_command": true}
"make a new layer called facade" -> {"macro": "_-Layer _New facade _Enter", "is_command": true}
"switch to layer facade" -> {"macro": "_-Layer _Current facade _Enter", "is_command": true}
"rotate selected 45 degrees around the origin" -> {"macro": "_Rotate 0,0,0 45", "is_command": true}
"scale this by 2" -> {"macro": "_Scale 0,0,0 2", "is_command": true}
"remind me to email the client" -> {"macro": "", "is_command": false}
"""


@dataclass
class LLMResult:
    macro: str
    is_command: bool
    raw: str


class Backend(Protocol):
    name: str

    def complete(self, messages: list[dict]) -> str: ...


def build_messages(text: str, commands_hint: list[str] | None = None) -> list[dict]:
    system = SYSTEM_PROMPT
    if commands_hint:
        system += "\nSome valid commands: " + ", ".join(commands_hint[:150]) + "\n"
    return [{"role": "system", "content": system}, {"role": "user", "content": text}]


def parse_reply(raw: str) -> LLMResult:
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        return LLMResult("", False, raw)
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return LLMResult("", False, raw)
    macro = str(data.get("macro") or "").strip()
    return LLMResult(macro, bool(data.get("is_command")) and bool(macro), raw)


class HFLocal:
    """Run an instruct model locally with transformers (loaded lazily on first use)."""

    name = "hf-local"

    def __init__(self, model: str = "Qwen/Qwen2.5-1.5B-Instruct", device: str | None = None):
        self.model_id = model
        self.device = device
        self._tok = None
        self._model = None

    def _load(self) -> None:
        if self._model is not None:
            return
        import torch  # noqa: PLC0415
        from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: PLC0415

        device = self.device or ("cuda" if torch.cuda.is_available()
                                 else "mps" if torch.backends.mps.is_available() else "cpu")
        self._tok = AutoTokenizer.from_pretrained(self.model_id)
        self._model = AutoModelForCausalLM.from_pretrained(
            self.model_id, torch_dtype="auto").to(device)
        self._model.eval()

    def complete(self, messages: list[dict]) -> str:
        self._load()
        import torch  # noqa: PLC0415

        prompt = self._tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self._tok(prompt, return_tensors="pt").to(self._model.device)
        with torch.no_grad():
            out = self._model.generate(**inputs, max_new_tokens=96, do_sample=False,
                                       pad_token_id=self._tok.eos_token_id)
        return self._tok.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)


class HFApi:
    """Call a model through Hugging Face Inference Providers."""

    name = "hf-api"

    def __init__(self, model: str = "Qwen/Qwen2.5-7B-Instruct", token: str | None = None):
        from huggingface_hub import InferenceClient  # noqa: PLC0415

        self.client = InferenceClient(model=model, token=token or os.environ.get("HF_TOKEN"))

    def complete(self, messages: list[dict]) -> str:
        resp = self.client.chat_completion(messages=messages, max_tokens=96, temperature=0.0)
        return resp.choices[0].message.content or ""


def make_backend(kind: str, model: str | None = None) -> Backend | None:
    if kind in ("none", "", None):
        return None
    if kind == "hf-local":
        return HFLocal(model) if model else HFLocal()
    if kind == "hf-api":
        return HFApi(model) if model else HFApi()
    raise ValueError(f"unknown LLM backend '{kind}' (use hf-local, hf-api or none)")


class LLMMapper:
    def __init__(self, backend: Backend):
        self.backend = backend

    def map(self, text: str, commands_hint: list[str] | None = None) -> LLMResult:
        return parse_reply(self.backend.complete(build_messages(text, commands_hint)))
