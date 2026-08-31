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


class TranscriptIn(BaseModel):
    format: str = "text"  # text | jsonl | ...
    text: str | None = None  # inline, or...
    uri: str | None = None  # ...a pointer to fetch
    source: str = "byo"


class JudgeConfigIn(BaseModel):
    base_url: str
    model: str
    api_key: str | None = None
    params: dict | None = None  # provider-specific passthrough (reasoning, temperature…)
    enabled: bool = True
