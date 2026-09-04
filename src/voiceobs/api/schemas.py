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
    api_key: str | None = None  # write-only; omit to keep the stored key
    prompt: str | None = None  # per-tenant system-prompt override; "" resets to the default
    params: dict | None = None  # provider-specific passthrough (reasoning, temperature…)
    enabled: bool = True


class SettingsIn(BaseModel):
    audio_analysis_enabled: bool | None = None  # null = defer to global default
    audio_store_prefix: str | None = None


class SignupIn(BaseModel):
    email: str
    password: str
    name: str | None = None
    org_name: str | None = None  # first org's display name; defaults to "Default"


class LoginIn(BaseModel):
    email: str
    password: str


class AcceptInviteIn(BaseModel):
    token: str
    password: str
    name: str | None = None


class MemberIn(BaseModel):
    email: str
    role: str = "member"  # owner | admin | member | viewer


class RoleIn(BaseModel):
    role: str


class OrgIn(BaseModel):
    name: str
    slug: str | None = None


class AudioConfigIn(BaseModel):
    enabled: bool = False
    s3_bucket: str | None = None
    s3_prefix: str | None = None
    s3_region: str | None = None
    s3_endpoint_url: str | None = None
    access_key_id: str | None = None
    secret_access_key: str | None = None  # write-only; omit to keep the stored secret
    # BYO STT for transcript verification (OpenAI-style /audio/transcriptions). Optional.
    stt_base_url: str | None = None
    stt_model: str | None = None
    stt_api_key: str | None = None  # write-only; omit to keep the stored key


class AgentIn(BaseModel):
    name: str
    slug: str | None = None
    audio: AudioConfigIn | None = None  # optional: configure audio at create time


class AgentPatchIn(BaseModel):
    name: str


class IngestTokenIn(BaseModel):
    name: str | None = None


class AgentAccessIn(BaseModel):
    agent_ids: list[str]  # replace the member's grant set (empty = coarse "all org agents")
