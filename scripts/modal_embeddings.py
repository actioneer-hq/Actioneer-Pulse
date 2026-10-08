"""Qwen3-Embedding-0.6B on Modal (T4), OpenAI-compatible: POST /v1/embeddings.

Pulse sends instruct-prefixed text itself (config `embedding_instruct`); this only embeds. Auth: a bearer
key from the Modal secret `pulse-embeddings` (EMBED_API_KEY) — the same value goes in Pulse's
VOICEOBS_EMBEDDING_API_KEY. Scales to zero when idle.

    modal secret create pulse-embeddings EMBED_API_KEY=<key>
    modal deploy scripts/modal_embeddings.py
    # then VOICEOBS_EMBEDDING_BASE_URL=https://<workspace>--pulse-embeddings-web.modal.run/v1
"""

import modal

MODEL = "Qwen/Qwen3-Embedding-0.6B"


def _download() -> None:
    from sentence_transformers import SentenceTransformer

    SentenceTransformer(MODEL)  # cached in the image, so containers start without a download


image = (modal.Image.debian_slim(python_version="3.12")
         .pip_install("sentence-transformers>=5.1", "fastapi>=0.115", "torch>=2.5")
         .run_function(_download))
app = modal.App("pulse-embeddings", image=image)


@app.function(gpu="T4", secrets=[modal.Secret.from_name("pulse-embeddings")], scaledown_window=300,
              max_containers=2)
@modal.concurrent(max_inputs=8)
@modal.asgi_app()
def web():
    import os

    from fastapi import FastAPI, HTTPException, Request
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(MODEL, device="cuda")
    key = os.environ["EMBED_API_KEY"]
    api = FastAPI()

    @api.post("/v1/embeddings")
    async def embeddings(request: Request) -> dict:
        if request.headers.get("authorization") != f"Bearer {key}":
            raise HTTPException(401, "bad key")
        body = await request.json()
        texts = [body["input"]] if isinstance(body.get("input"), str) else list(body.get("input") or [])
        vectors = model.encode(texts, normalize_embeddings=True, batch_size=32)
        return {"object": "list", "model": MODEL,
                "data": [{"object": "embedding", "index": i, "embedding": v.tolist()} for i, v in enumerate(vectors)],
                "usage": {"prompt_tokens": 0, "total_tokens": 0}}

    return api
