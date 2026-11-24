"""Example: Hugging Face models (or any Python) as Grasshopper components, through Hops.

Hops can call a Python function over HTTP as if it were a component. This small server gives
Grasshopper two components:

    /ask      text prompt -> text answer from a Hugging Face model (needs HF_TOKEN)
    /rank     a brief + a list of option descriptions -> the options ordered by how well they
              fit the brief, with scores (sentence embeddings, also through Hugging Face)

Run it (in the kazi-rhino virtual environment):

    pip install ghhops-server flask huggingface_hub
    set HF_TOKEN=hf_...                      (PowerShell: $env:HF_TOKEN = "hf_...")
    python examples/hops_hf_server.py

Then in Grasshopper place a Hops component and set its Path to http://127.0.0.1:5000/ask
(or say: "add a hops component for http://127.0.0.1:5000/ask").
"""

import os

import ghhops_server as hs
from flask import Flask

app = Flask(__name__)
hops = hs.Hops(app)

CHAT_MODEL = os.environ.get("KAZI_HOPS_CHAT_MODEL", "Qwen/Qwen2.5-7B-Instruct")
EMBED_MODEL = os.environ.get("KAZI_HOPS_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")


def _client():
    from huggingface_hub import InferenceClient  # imported late so the server starts without it

    return InferenceClient(token=os.environ.get("HF_TOKEN"))


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = sum(x * x for x in a) ** 0.5, sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


@hops.component(
    "/ask", name="Ask", nickname="Ask", description="Ask a Hugging Face model a question",
    inputs=[hs.HopsString("Prompt", "P", "What to ask")],
    outputs=[hs.HopsString("Answer", "A", "The model's answer")])
def ask(prompt):
    reply = _client().chat_completion(model=CHAT_MODEL, max_tokens=400,
                                      messages=[{"role": "user", "content": prompt}])
    return reply.choices[0].message.content


@hops.component(
    "/rank", name="Rank options", nickname="Rank",
    description="Order design option descriptions by how well they fit a brief",
    inputs=[hs.HopsString("Brief", "B", "What you are looking for"),
            hs.HopsString("Options", "O", "One description per option", hs.HopsParamAccess.LIST)],
    outputs=[hs.HopsInteger("Order", "I", "Option indices, best first", hs.HopsParamAccess.LIST),
             hs.HopsNumber("Score", "S", "Fit of each option, in the input order", hs.HopsParamAccess.LIST)])
def rank(brief, options):
    client = _client()
    target = list(map(float, client.feature_extraction(brief, model=EMBED_MODEL)))
    scores = [_cosine(target, list(map(float, client.feature_extraction(o, model=EMBED_MODEL))))
              for o in options]
    order = sorted(range(len(options)), key=lambda i: -scores[i])
    return order, scores


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
