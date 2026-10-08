"""Local OpenAI-compatible embeddings server for development (Qwen3-Embedding-0.6B by default).

Pulse sends instruct-prefixed text itself (config `embedding_instruct`), so this only embeds what it is
given. Point Pulse at it with VOICEOBS_EMBEDDING_BASE_URL=http://host.docker.internal:8765/v1 (from
Docker) or http://localhost:8765/v1, and any non-empty VOICEOBS_EMBEDDING_API_KEY.

    uv run --no-project --with sentence-transformers --with fastapi --with uvicorn \\
        python scripts/local_embeddings.py [--model Qwen/Qwen3-Embedding-0.6B] [--port 8765]
"""

from __future__ import annotations

import argparse

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer


class EmbeddingsIn(BaseModel):
    input: str | list[str]
    model: str | None = None


def app_for(model_name: str) -> FastAPI:
    model = SentenceTransformer(model_name)
    app = FastAPI()

    @app.post("/v1/embeddings")
    def embeddings(body: EmbeddingsIn) -> dict:
        texts = [body.input] if isinstance(body.input, str) else body.input
        vectors = model.encode(texts, normalize_embeddings=True, batch_size=32)
        return {"object": "list", "model": model_name,
                "data": [{"object": "embedding", "index": i, "embedding": v.tolist()}
                         for i, v in enumerate(vectors)],
                "usage": {"prompt_tokens": 0, "total_tokens": 0}}

    return app


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="Qwen/Qwen3-Embedding-0.6B")
    p.add_argument("--port", type=int, default=8765)
    a = p.parse_args()
    uvicorn.run(app_for(a.model), host="0.0.0.0", port=a.port)
