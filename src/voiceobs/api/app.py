"""VO API — OTLP ingest + read endpoints. Serves the viewer; never touches audio bytes."""

from __future__ import annotations

from fastapi import FastAPI

from voiceobs.api import ingest, read

app = FastAPI(title="Voice Observability")
app.include_router(ingest.router)
app.include_router(read.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
