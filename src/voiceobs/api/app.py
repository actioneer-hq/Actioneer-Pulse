"""Pulse API — OTLP ingest + read endpoints, and the built UI. Never touches audio bytes."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from voiceobs.api import (
    agents,
    auth,
    boards,
    chat,
    clusters,
    ingest,
    judge,
    orgs,
    read,
    settings,
)

app = FastAPI(title="Pulse")
app.include_router(auth.router)
app.include_router(orgs.router)
app.include_router(agents.router)
app.include_router(boards.router)
app.include_router(clusters.router)
app.include_router(chat.router)
app.include_router(ingest.router)
app.include_router(read.router)
app.include_router(judge.router)
app.include_router(settings.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# The built SPA. Real assets are served by StaticFiles; any other GET falls back to
# index.html so client-side routes (/calls, /settings/…) survive a hard refresh. Both are
# declared last, on purpose — a catch-all at "/" shadows every route declared after it.
# Absent in a source checkout until `npm --prefix ui run build`, so the API still starts
# (and every test still passes) without the UI built.
_UI = Path(__file__).parent / "static"
if _UI.is_dir():
    app.mount("/assets", StaticFiles(directory=_UI / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str) -> FileResponse:
        # Never swallow the API surface: a request under an API prefix that matched no route
        # above is a genuine 404, not a client route to hand back to the SPA.
        if path == "health" or path.split("/", 1)[0] in {"v1", "assets"}:
            raise HTTPException(404, "not found")
        file = _UI / path
        if path and file.is_file():
            return FileResponse(file)
        index = _UI / "index.html"
        if not index.is_file():
            raise HTTPException(404, "not found")
        return FileResponse(index)
