"""Request bodies for the ingest API. Read responses are shaped inline."""

from __future__ import annotations

from pydantic import BaseModel


class ArtifactIn(BaseModel):
    kind: str  # audio | peaks | events_jsonl | segments | artifact_json
    uri: str | None = None
    sha256: str | None = None
    bytes: int | None = None
    content_type: str | None = None
    channels: int | None = None
    sample_rate: int | None = None
    channel_map: dict[int, str] | None = None
    t0_offset_s: float | None = None


class PromptIn(BaseModel):
    template_sha256: str
    text: str
