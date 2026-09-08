"""The ingest service deployable — a thin FastAPI app that mounts ONLY the ingest router (the Kafka
producer path). Separate from the read/dashboard API so it scales and fails independently; a future
Go rewrite replaces this process while speaking the same `raw-spans` contract.

Run: `uvicorn voiceobs.ingest_app:app`. (The all-in-one `voiceobs.api.app:app` still exists for local
dev + tests.)"""

from __future__ import annotations

from fastapi import FastAPI

from voiceobs.api import ingest

app = FastAPI(title="Pulse ingest")
app.include_router(ingest.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
