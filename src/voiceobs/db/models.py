"""Pulse Postgres schema — SQLAlchemy 2.0 ORM, mirroring MODELS.md.

Thirteen tables. ``tenant_id`` on every one. Load-bearing constraints (idempotency
and the daily metric-predicate query) are declared explicitly, not left implicit:

- ``Call``    UNIQUE (tenant_id, external_call_id) — re-delivery is expected
- ``Metric``  UNIQUE (call_id, name, metric_version) + INDEX (tenant_id, name, value_num)
- ``Media``   UNIQUE (call_id, kind, sha256)
- ``Turn``    UNIQUE (call_id, turn_index)
- ``Annotation`` UNIQUE (call_id, kind, source, body_sha256) — append-log, never upsert
- ``Prompt``  UNIQUE (tenant_id, template_sha256) — templates only
- ``Tombstone`` PK (tenant_id, call_id) — written first in DELETE, blocks resurrection

Content columns (``Event.content_text``/``content_kind``; ``Turn`` transcript
columns) are kept apart from shape so ``DELETE`` finds text in one place.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from voiceobs.db.base import Base, created_col, pk, tenant_col

_CALL_FK = "call.id"


class Prompt(Base):
    """TEMPLATES ONLY. The compiled prompt (template + recipient PII) lives in the
    call artifact, erased with the call. Never here."""

    __tablename__ = "prompt"
    __table_args__ = (UniqueConstraint("tenant_id", "template_sha256", name="uq_prompt_template"),)

    id: Mapped[str] = pk()
    tenant_id: Mapped[str] = tenant_col()
    template_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    first_seen_at: Mapped[datetime] = created_col()


class Call(Base):
    __tablename__ = "call"
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_call_id", name="uq_call_external"),
        Index("ix_call_tenant_env_started", "tenant_id", "environment", "started_at"),
        Index("ix_call_status_activity", "status", "last_activity_at"),
        Index("ix_call_tenant_trace", "tenant_id", "trace_id"),
    )

    id: Mapped[str] = pk()
    tenant_id: Mapped[str] = tenant_col()
    external_call_id: Mapped[str] = mapped_column(String(128), nullable=False)  # voice.call_id
    # OTLP trace id — the only call identity every producer has. Spans arriving in a
    # later batch than the root resolve back to this call through it.
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)  # resource service.name
    environment: Mapped[str] = mapped_column(String(16), nullable=False)
    schema_version: Mapped[int | None] = mapped_column(Integer)

    engine: Mapped[str | None] = mapped_column(String(16))  # cascade | s2s
    carrier: Mapped[str | None] = mapped_column(String(32))  # exotel | plivo
    stt_provider: Mapped[str | None] = mapped_column(String(64))
    llm_provider: Mapped[str | None] = mapped_column(String(64))
    tts_provider: Mapped[str | None] = mapped_column(String(64))
    voice: Mapped[str | None] = mapped_column(String(64))
    campaign_id: Mapped[str | None] = mapped_column(String(128))
    prompt_id: Mapped[str | None] = mapped_column(ForeignKey("prompt.id"))
    labels: Mapped[dict | None] = mapped_column(JSON)  # opaque — the OSS boundary

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_s: Mapped[float | None] = mapped_column(Float)

    # audio <-> span join. RECORDED, may be negative, never a constant, never clamp.
    audio_t0_offset_s: Mapped[float | None] = mapped_column(Float)
    audio_t0_epoch_ns: Mapped[int | None] = mapped_column(Integer)
    channel_map: Mapped[dict | None] = mapped_column(JSON)  # {"0":"caller","1":"agent"}
    sample_rate: Mapped[int | None] = mapped_column(Integer)

    # outcome (worker-known; carrier truth arrives via Annotation later)
    terminal_reason: Mapped[str | None] = mapped_column(String(64))
    hangup_by: Mapped[str | None] = mapped_column(String(16))  # agent | remote | error
    stream_duration_s: Mapped[float | None] = mapped_column(Float)

    # cost — raw units always stored (INR)
    cost_llm: Mapped[float | None] = mapped_column(Float)
    cost_stt: Mapped[float | None] = mapped_column(Float)
    cost_tts: Mapped[float | None] = mapped_column(Float)
    cost_total: Mapped[float | None] = mapped_column(Float)
    cost_currency: Mapped[str | None] = mapped_column(String(8))
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    tokens_cached: Mapped[int | None] = mapped_column(Integer)
    tts_chars: Mapped[int | None] = mapped_column(Integer)
    tts_chars_cut: Mapped[int | None] = mapped_column(Integer)
    stt_seconds: Mapped[float | None] = mapped_column(Float)

    # telemetry coverage — counters authoritative, events lossy
    stt_segments_heard: Mapped[int | None] = mapped_column(Integer)
    stt_segments_overheard: Mapped[int | None] = mapped_column(Integer)
    stt_segments_dropped: Mapped[int | None] = mapped_column(Integer)
    span_dropped_events: Mapped[int | None] = mapped_column(Integer)
    unattributed_spans: Mapped[int | None] = mapped_column(Integer)
    service_instance_id: Mapped[str | None] = mapped_column(String(64))
    # which registered agent produced this call (loose ref to agent.id, like tenant_id ->
    # organization.id; nullable for dev-open / pre-identity calls).
    agent_id: Mapped[str | None] = mapped_column(String(36), index=True)

    # gates + status
    spans_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    media_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(24), default="awaiting_media")
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bookmarked: Mapped[bool] = mapped_column(Boolean, default=False)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    retention_days: Mapped[int | None] = mapped_column(Integer)

    app_version: Mapped[str | None] = mapped_column(String(64))
    metric_version: Mapped[int | None] = mapped_column(Integer)
    adapter_version: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = created_col()


class RawFragment(Base):
    """Raw OTLP wire payload, sharded per call at ingest. The reprocess source —
    a schema bump that renames a previously-dropped attribute is recoverable.
    call_id NULL = spans with no call_id -> surfaced as unattributed_spans."""

    __tablename__ = "raw_fragment"
    __table_args__ = (Index("ix_rawfragment_call_batch_seq", "call_id", "batch_id", "seq"),)

    id: Mapped[str] = pk()
    call_id: Mapped[str | None] = mapped_column(ForeignKey(_CALL_FK))
    tenant_id: Mapped[str] = tenant_col()
    batch_id: Mapped[str | None] = mapped_column(String(64))
    seq: Mapped[int | None] = mapped_column(Integer)
    received_at: Mapped[datetime] = created_col()
    payload_gz: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    schema_version: Mapped[int | None] = mapped_column(Integer)


class Event(Base):
    """Adapted spans + span events. Shape in attrs; conversation text in content_*."""

    __tablename__ = "event"
    __table_args__ = (
        Index("ix_event_call_t", "call_id", "t_offset_s"),
        Index("ix_event_call_span", "call_id", "span_id"),
    )

    id: Mapped[str] = pk()
    call_id: Mapped[str] = mapped_column(ForeignKey(_CALL_FK), nullable=False)
    tenant_id: Mapped[str] = tenant_col()
    span_id: Mapped[str | None] = mapped_column(String(64))
    parent_span_id: Mapped[str | None] = mapped_column(String(64))  # null = root
    turn_id: Mapped[str | None] = mapped_column(String(160))  # NULLABLE BY DESIGN
    t_offset_s: Mapped[float | None] = mapped_column(Float)  # seconds from call t0
    kind: Mapped[str] = mapped_column(String(8), nullable=False)  # span | event
    type: Mapped[str] = mapped_column(String(48), nullable=False)  # normalized stage or event name
    name: Mapped[str | None] = mapped_column(String(64))  # the producer's own span/event name
    duration_s: Mapped[float | None] = mapped_column(Float)  # spans only; None = never closed
    error: Mapped[bool | None] = mapped_column(Boolean)  # span failed (status ERROR / exception)
    attrs: Mapped[dict | None] = mapped_column(JSON)  # SHAPE only, allowlisted
    content_text: Mapped[str | None] = mapped_column(Text)  # from voice.content.* — own column
    content_kind: Mapped[str | None] = mapped_column(String(24))  # transcript|llm_raw|llm_spoken


class Utterance(Base):
    """FROM AUDIO. Contiguous speech on one channel, per-channel VAD on the stereo WAV."""

    __tablename__ = "utterance"
    __table_args__ = (Index("ix_utterance_call_start", "call_id", "t_start_s"),)

    id: Mapped[str] = pk()
    call_id: Mapped[str] = mapped_column(ForeignKey(_CALL_FK), nullable=False)
    tenant_id: Mapped[str] = tenant_col()
    channel: Mapped[str] = mapped_column(String(16), nullable=False)  # caller | agent
    t_start_s: Mapped[float] = mapped_column(Float, nullable=False)
    t_end_s: Mapped[float] = mapped_column(Float, nullable=False)
    metric_version: Mapped[int | None] = mapped_column(Integer)


class Turn(Base):
    """FROM SPANS. One EXCHANGE. NO speaker field. Joined to utterances by overlap."""

    __tablename__ = "turn"
    __table_args__ = (UniqueConstraint("call_id", "turn_index", name="uq_turn_index"),)

    id: Mapped[str] = pk()
    call_id: Mapped[str] = mapped_column(ForeignKey(_CALL_FK), nullable=False)
    tenant_id: Mapped[str] = tenant_col()
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    turn_id: Mapped[str | None] = mapped_column(String(160))  # "<call_id>:<n>"
    trigger: Mapped[str | None] = mapped_column(String(16))  # opening | endpoint
    interrupted: Mapped[bool | None] = mapped_column(Boolean)
    abandoned: Mapped[bool | None] = mapped_column(Boolean)

    # from spans, offset-corrected to audio clock
    stt_final_at: Mapped[float | None] = mapped_column(Float)
    committed_at: Mapped[float | None] = mapped_column(Float)
    llm_first_token_at: Mapped[float | None] = mapped_column(Float)
    tts_start_at: Mapped[float | None] = mapped_column(Float)
    tts_first_audio_at: Mapped[float | None] = mapped_column(Float)
    caller_utt_end_s: Mapped[float | None] = mapped_column(Float)
    agent_utt_start_s: Mapped[float | None] = mapped_column(Float)

    # the waterfall
    response_latency_ms: Mapped[float | None] = mapped_column(Float)
    stt_lag_ms: Mapped[float | None] = mapped_column(Float)
    endpointing_ms: Mapped[float | None] = mapped_column(Float)
    llm_ttft_ms: Mapped[float | None] = mapped_column(Float)
    assembly_ms: Mapped[float | None] = mapped_column(Float)
    dispatch_ms: Mapped[float | None] = mapped_column(Float)  # first token -> TTS request
    tts_ttfb_ms: Mapped[float | None] = mapped_column(Float)
    playout_ms: Mapped[float | None] = mapped_column(Float)
    unattributed_ms: Mapped[float | None] = mapped_column(Float)
    llm_ttft_reported_ms: Mapped[float | None] = mapped_column(Float)  # producer attr
    tts_ttfb_reported_ms: Mapped[float | None] = mapped_column(Float)

    language: Mapped[str | None] = mapped_column(String(16))
    stt_confidence: Mapped[float | None] = mapped_column(Float)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    tokens_cached: Mapped[int | None] = mapped_column(Integer)
    finish_reason: Mapped[str | None] = mapped_column(String(32))
    tts_chars: Mapped[int | None] = mapped_column(Integer)
    tts_chars_cut: Mapped[int | None] = mapped_column(Integer)
    tts_cancelled: Mapped[bool | None] = mapped_column(Boolean)  # speech cut off mid-synthesis
    cut_reason: Mapped[str | None] = mapped_column(String(16))  # barge_in | hangup
    tts_span_present: Mapped[bool | None] = mapped_column(Boolean)
    interruption_probability: Mapped[float | None] = mapped_column(Float)  # producer's own
    e2e_latency_ms: Mapped[float | None] = mapped_column(Float)  # engine's own end-to-end

    # content — from span content when sent, else artifact
    caller_transcript: Mapped[str | None] = mapped_column(Text)
    llm_raw: Mapped[str | None] = mapped_column(Text)
    llm_spoken: Mapped[str | None] = mapped_column(Text)
    metric_version: Mapped[int | None] = mapped_column(Integer)


class Metric(Base):
    __tablename__ = "metric"
    __table_args__ = (
        UniqueConstraint("call_id", "name", "metric_version", name="uq_metric_name_version"),
        Index("ix_metric_tenant_name_value", "tenant_id", "name", "value_num"),
    )

    id: Mapped[str] = pk()
    call_id: Mapped[str] = mapped_column(ForeignKey(_CALL_FK), nullable=False)
    tenant_id: Mapped[str] = tenant_col()
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    value_num: Mapped[float | None] = mapped_column(Float)
    value_text: Mapped[str | None] = mapped_column(String(128))
    samples: Mapped[list | None] = mapped_column(JSON)  # per-turn series
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    reason: Mapped[str | None] = mapped_column(String(128))
    metric_version: Mapped[int] = mapped_column(Integer, nullable=False)


class MetricDef(Base):
    __tablename__ = "metric_def"

    id: Mapped[str] = pk()
    tenant_id: Mapped[str] = tenant_col()
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(16))
    data_type: Mapped[str | None] = mapped_column(String(16))
    min_value: Mapped[float | None] = mapped_column(Float)
    max_value: Mapped[float | None] = mapped_column(Float)
    higher_is_better: Mapped[bool | None] = mapped_column(Boolean)
    description: Mapped[str | None] = mapped_column(Text)
    metric_version: Mapped[int | None] = mapped_column(Integer)


class Media(Base):
    """Pointers, not bytes — except peaks."""

    __tablename__ = "media"
    __table_args__ = (UniqueConstraint("call_id", "kind", "sha256", name="uq_media_kind_sha"),)

    id: Mapped[str] = pk()
    call_id: Mapped[str] = mapped_column(ForeignKey(_CALL_FK), nullable=False)
    tenant_id: Mapped[str] = tenant_col()
    kind: Mapped[str] = mapped_column(String(24), nullable=False)  # audio|artifact_json|peaks|...
    uri: Mapped[str | None] = mapped_column(String(1024))  # gs:// or s3://
    peaks: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)  # int16 min/max
    sha256: Mapped[str | None] = mapped_column(String(64))
    bytes: Mapped[int | None] = mapped_column(Integer)
    content_type: Mapped[str | None] = mapped_column(String(64))
    channels: Mapped[int | None] = mapped_column(Integer)
    sample_rate: Mapped[int | None] = mapped_column(Integer)


class IngestRun(Base):
    __tablename__ = "ingest_run"
    __table_args__ = (Index("ix_ingestrun_call_metric", "call_id", "metric_version"),)

    id: Mapped[str] = pk()
    call_id: Mapped[str] = mapped_column(ForeignKey(_CALL_FK), nullable=False)
    tenant_id: Mapped[str] = tenant_col()
    app_version: Mapped[str | None] = mapped_column(String(64))
    metric_version: Mapped[int | None] = mapped_column(Integer)
    adapter_version: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str | None] = mapped_column(String(16))  # running|ok|failed|partial
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class Annotation(Base):
    """Post-hoc, from any process, APPEND-LOG — never upsert. Body is pipe-2 PII."""

    __tablename__ = "annotation"
    __table_args__ = (
        UniqueConstraint("call_id", "kind", "source", "body_sha256", name="uq_annotation_body"),
    )

    id: Mapped[str] = pk()
    call_id: Mapped[str] = mapped_column(ForeignKey(_CALL_FK), nullable=False)
    tenant_id: Mapped[str] = tenant_col()
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    source: Mapped[str] = mapped_column(String(48), nullable=False)
    at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    body: Mapped[dict | None] = mapped_column(JSON)
    body_sha256: Mapped[str] = mapped_column(String(64), nullable=False)  # idempotency key


class Label(Base):
    """Human annotations. Empty for now."""

    __tablename__ = "label"

    id: Mapped[str] = pk()
    call_id: Mapped[str] = mapped_column(ForeignKey(_CALL_FK), nullable=False)
    turn_id: Mapped[str | None] = mapped_column(String(160))
    tenant_id: Mapped[str] = tenant_col()
    name: Mapped[str | None] = mapped_column(String(64))
    value: Mapped[str | None] = mapped_column(String(256))
    user_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_col()


class Transcript(Base):
    """BYO transcript for a call. One per call (re-upload replaces). When present it
    overrides the transcript derived from turn content; feeds the post-call judge."""

    __tablename__ = "transcript"
    __table_args__ = (UniqueConstraint("call_id", name="uq_transcript_call"),)

    id: Mapped[str] = pk()
    call_id: Mapped[str] = mapped_column(ForeignKey(_CALL_FK), nullable=False)
    tenant_id: Mapped[str] = tenant_col()
    source: Mapped[str] = mapped_column(String(32), default="byo")
    format: Mapped[str | None] = mapped_column(String(24))  # text | jsonl | ...
    content: Mapped[str | None] = mapped_column(Text)  # inline transcript
    uri: Mapped[str | None] = mapped_column(String(1024))  # or a pointer to fetch
    created_at: Mapped[datetime] = created_col()


class TenantSettings(Base):
    """Per-tenant platform switches. Audio analysis is off by default (OTLP-only); turning
    it on requires access to the client's audio store (S3), pointed at by audio_store_prefix.
    A null flag means "defer to the global VOICEOBS_AUDIO_ANALYSIS default"."""

    __tablename__ = "tenant_settings"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_tenant_settings_tenant"),)

    id: Mapped[str] = pk()
    tenant_id: Mapped[str] = tenant_col()
    audio_analysis_enabled: Mapped[bool | None] = mapped_column(Boolean)
    audio_store_prefix: Mapped[str | None] = mapped_column(String(1024))
    created_at: Mapped[datetime] = created_col()
    updated_at: Mapped[datetime] = created_col()


class Judgment(Base):
    """Post-call structured judgment. Disposition is programmatic; the rest is the LLM's
    output (null when the call was never connected)."""

    __tablename__ = "judgment"
    __table_args__ = (UniqueConstraint("call_id", name="uq_judgment_call"),)

    id: Mapped[str] = pk()
    call_id: Mapped[str] = mapped_column(ForeignKey(_CALL_FK), nullable=False)
    tenant_id: Mapped[str] = tenant_col()

    disposition: Mapped[str | None] = mapped_column(String(32))  # programmatic
    status: Mapped[str] = mapped_column(String(16), default="skipped")  # ok|skipped|failed
    model: Mapped[str | None] = mapped_column(String(128))
    error: Mapped[str | None] = mapped_column(Text)

    # LLM fields (null unless connected + judged)
    sentiment: Mapped[str | None] = mapped_column(String(16))
    objective_achieved: Mapped[str | None] = mapped_column(String(16))
    answered_by: Mapped[str | None] = mapped_column(String(16))
    primary_language: Mapped[str | None] = mapped_column(String(32))
    secondary_languages: Mapped[list | None] = mapped_column(JSON)
    script_adherence: Mapped[str | None] = mapped_column(String(16))
    escalation_requested: Mapped[bool | None] = mapped_column(Boolean)
    callback_requested: Mapped[bool | None] = mapped_column(Boolean)
    callback_time: Mapped[str | None] = mapped_column(String(128))
    guardrail_violation: Mapped[bool | None] = mapped_column(Boolean)
    guardrail_violation_points: Mapped[list | None] = mapped_column(JSON)  # only when violation
    summary: Mapped[str | None] = mapped_column(Text)
    judged_at: Mapped[datetime] = created_col()


class Tombstone(Base):
    """Erased calls. Written FIRST in DELETE so a crash mid-erasure leaves an
    un-resurrectable call. Ingest checks it: a straggling re-POST is dropped."""

    __tablename__ = "tombstone"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    call_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    deleted_at: Mapped[datetime] = created_col()
    deleted_by: Mapped[str | None] = mapped_column(String(64))


# ── Identity / RBAC / agents ────────────────────────────────────────────────────
# These define and scope tenancy (org = tenant_id) rather than carry it, so they use
# real FKs among themselves and do NOT use tenant_col(). Data tables above stay on the
# loose `tenant_id` string (= Organization.id) — see CONTRACTS / the identity plan.


class Organization(Base):
    """A tenant. Its `id` IS the `tenant_id` stamped on every data row. The self-host
    default org is seeded with id="default"."""

    __tablename__ = "organization"

    id: Mapped[str] = pk()
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = created_col()


class AppUser(Base):
    """A person who can sign in. `password_hash` is nullable so SSO-only users work later.
    Table name is `app_user` — `user` is reserved in Postgres."""

    __tablename__ = "app_user"

    id: Mapped[str] = pk()
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)  # store lowercased
    password_hash: Mapped[str | None] = mapped_column(String(255))
    name: Mapped[str | None] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = created_col()


class Membership(Base):
    """A user's place in an org, with a coarse role. Granular per-agent access is layered
    on top via AgentAccess."""

    __tablename__ = "membership"
    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_membership"),
        Index("ix_membership_user", "user_id"),
        Index("ix_membership_org", "org_id"),
    )

    id: Mapped[str] = pk()
    org_id: Mapped[str] = mapped_column(ForeignKey("organization.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # owner|admin|member|viewer
    created_at: Mapped[datetime] = created_col()


class Agent(Base):
    """A deployed voice agent — the "project" and the OTLP routing target. Its `id` is what
    a producer stamps as voiceobs.agent_id and what an ingest token resolves to."""

    __tablename__ = "agent"
    __table_args__ = (
        UniqueConstraint("org_id", "slug", name="uq_agent_slug"),
        Index("ix_agent_org", "org_id"),
    )

    id: Mapped[str] = pk()
    org_id: Mapped[str] = mapped_column(ForeignKey("organization.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = created_col()


class Conversation(Base):
    """A saved global-chat thread. Belongs to an org + its creator; the sidebar lists these."""

    __tablename__ = "conversation"
    __table_args__ = (Index("ix_conversation_owner", "tenant_id", "created_by"),)

    id: Mapped[str] = pk()
    tenant_id: Mapped[str] = tenant_col()
    created_by: Mapped[str | None] = mapped_column(ForeignKey("app_user.id"))
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="New chat")
    created_at: Mapped[datetime] = created_col()
    updated_at: Mapped[datetime] = created_col()


class ChatMessage(Base):
    """One turn in a conversation. `steps` holds the assistant turn's tool-call activity
    (name/args/summary), so the thread can replay 'the agent searched calls…' on reload."""

    __tablename__ = "chat_message"
    __table_args__ = (
        UniqueConstraint("conversation_id", "seq", name="uq_chat_message_seq"),
        Index("ix_chat_message_conv", "conversation_id", "seq"),
    )

    id: Mapped[str] = pk()
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversation.id"), nullable=False)
    tenant_id: Mapped[str] = tenant_col()
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    steps: Mapped[list | None] = mapped_column(JSON)  # tool-call activity for assistant turns
    created_at: Mapped[datetime] = created_col()


class AgentScript(Base):
    """A versioned pointer to the script (system prompt) an agent is meant to follow. Content is
    the immutable, hash-addressed Prompt; this row adds per-agent version + author + active flag,
    so history is auditable and each call pins the version it ran under. Exactly one active row
    per agent (enforced in code)."""

    __tablename__ = "agent_script"
    __table_args__ = (
        UniqueConstraint("agent_id", "version", name="uq_agent_script_version"),
        Index("ix_agent_script_active", "agent_id", "active"),
    )

    id: Mapped[str] = pk()
    agent_id: Mapped[str] = mapped_column(ForeignKey("agent.id"), nullable=False)
    prompt_id: Mapped[str] = mapped_column(ForeignKey("prompt.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("app_user.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = created_col()


class AgentGuardrail(Base):
    """A versioned pointer to an agent's guardrails — natural-language rules the agent must obey
    (stay on script, verify the user before tool calls, etc.), checked later as simple NLI. Mirrors
    AgentScript: content is the immutable hash-addressed Prompt; this row adds per-agent version +
    author + active flag. Exactly one active row per agent (enforced in code)."""

    __tablename__ = "agent_guardrail"
    __table_args__ = (
        UniqueConstraint("agent_id", "version", name="uq_agent_guardrail_version"),
        Index("ix_agent_guardrail_active", "agent_id", "active"),
    )

    id: Mapped[str] = pk()
    agent_id: Mapped[str] = mapped_column(ForeignKey("agent.id"), nullable=False)
    prompt_id: Mapped[str] = mapped_column(ForeignKey("prompt.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("app_user.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = created_col()


class AgentAccess(Base):
    """A granular grant: this membership may see this agent. A member with ZERO grants sees
    ALL org agents (coarse default); with ≥1, is restricted to the granted set."""

    __tablename__ = "agent_access"
    __table_args__ = (UniqueConstraint("membership_id", "agent_id", name="uq_agent_access"),)

    id: Mapped[str] = pk()
    membership_id: Mapped[str] = mapped_column(ForeignKey("membership.id"), nullable=False)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agent.id"), nullable=False)
    created_at: Mapped[datetime] = created_col()


class IngestToken(Base):
    """A per-agent ingest credential (Sentry-DSN style). The plaintext `vo_<prefix>_<secret>`
    is shown once at mint; only its argon2 hash is stored. Resolves to (org_id, agent_id)."""

    __tablename__ = "ingest_token"
    __table_args__ = (Index("ix_ingest_token_prefix", "token_prefix"),)

    id: Mapped[str] = pk()
    org_id: Mapped[str] = mapped_column(ForeignKey("organization.id"), nullable=False)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agent.id"), nullable=False)
    token_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str | None] = mapped_column(String(128))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_col()


class AudioDiscrepancy(Base):
    """One reconciled field where the audio ground truth disagrees with the OTLP self-report.
    Written by the ground-truth service; surfaced in the call inspector. Rewritten each analysis
    (deleted + reinserted), like metrics."""

    __tablename__ = "audio_discrepancy"
    __table_args__ = (Index("ix_audio_discrepancy_call", "call_id"),)

    id: Mapped[str] = pk()
    call_id: Mapped[str] = mapped_column(ForeignKey(_CALL_FK), nullable=False)
    tenant_id: Mapped[str] = tenant_col()
    turn_index: Mapped[int | None] = mapped_column(Integer)
    dimension: Mapped[str] = mapped_column(String(32), nullable=False)
    field: Mapped[str] = mapped_column(String(64), nullable=False)
    reported: Mapped[str | None] = mapped_column(Text)
    measured: Mapped[str | None] = mapped_column(Text)
    delta: Mapped[float | None] = mapped_column(Float)
    band: Mapped[float | None] = mapped_column(Float)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_col()


class AgentAudioConfig(Base):
    """Per-agent audio-analysis config (pull path). When `enabled`, a reconcile worker scans
    `s3://{s3_bucket}/{s3_prefix}` with these creds and attaches recordings to calls, matching
    on the call_id (= OTLP trace_id) embedded in the key: `<prefix>/<call_id>/audio.wav`.
    `secret_ciphertext` is the Fernet-encrypted secret access key — write-only over the API,
    never echoed."""

    __tablename__ = "agent_audio_config"
    __table_args__ = (UniqueConstraint("agent_id", name="uq_agent_audio_config_agent"),)

    id: Mapped[str] = pk()
    agent_id: Mapped[str] = mapped_column(ForeignKey("agent.id"), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    s3_bucket: Mapped[str | None] = mapped_column(String(255))
    s3_prefix: Mapped[str | None] = mapped_column(String(1024))
    s3_region: Mapped[str | None] = mapped_column(String(64))
    s3_endpoint_url: Mapped[str | None] = mapped_column(String(512))  # MinIO / R2 / etc.
    access_key_id: Mapped[str | None] = mapped_column(String(128))
    secret_ciphertext: Mapped[str | None] = mapped_column(Text)  # Fernet blob
    # BYO STT for transcript verification — an OpenAI-style /audio/transcriptions endpoint.
    # Optional: absent = transcript reconciliation is skipped gracefully. Key encrypted at rest.
    stt_base_url: Mapped[str | None] = mapped_column(String(512))
    stt_model: Mapped[str | None] = mapped_column(String(128))
    stt_key_ciphertext: Mapped[str | None] = mapped_column(Text)  # Fernet blob
    created_at: Mapped[datetime] = created_col()
    updated_at: Mapped[datetime] = created_col()


class RefreshToken(Base):
    """A revocable login session. The rotating plaintext `vor_<prefix>_<secret>` lives only in
    the httpOnly refresh cookie; only its argon2 hash is stored. `family_id` groups the rotation
    chain — presenting a revoked token revokes the whole family (theft response). Access JWTs are
    stateless and short; revocation happens here."""

    __tablename__ = "refresh_token"
    __table_args__ = (
        Index("ix_refresh_token_prefix", "token_prefix"),
        Index("ix_refresh_token_user", "user_id"),
        Index("ix_refresh_token_family", "family_id"),
    )

    id: Mapped[str] = pk()
    user_id: Mapped[str] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    family_id: Mapped[str] = mapped_column(String(36), nullable=False)
    token_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = created_col()
