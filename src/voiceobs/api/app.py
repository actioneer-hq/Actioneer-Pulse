"""VO API — OTLP ingest + read endpoints, and the built UI. Never touches audio bytes."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from voiceobs.api import ingest, judge, read, settings

app = FastAPI(title="Voice Observability")
app.include_router(ingest.router)
app.include_router(read.router)
app.include_router(judge.router)
app.include_router(settings.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# Mounted last, on purpose: a catch-all at "/" shadows every route declared after it.
# Absent in a source checkout until `npm --prefix ui run build`, so the API still
# starts (and every test still passes) without the UI built.
_UI = Path(__file__).parent / "static"
if _UI.is_dir():
    app.mount("/", StaticFiles(directory=_UI, html=True), name="ui")
