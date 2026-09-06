"""Internal types the pipeline produces after a framework adapter runs. See CONTRACTS.md."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Stage(StrEnum):
    CALL = "call"
    TURN = "turn"
    SPEECH = "speech"  # caller audibly speaking (VAD), before any transcript exists
    STT = "stt"
    LLM = "llm"
    TTS = "tts"
    PLAYOUT = "playout"  # synthesized audio actually reaching the caller
    TOOL = "tool"
    NET = "net"
    UNKNOWN = "unknown"  # producer emitted a name no adapter maps; never silently `net`


class TrustReason(StrEnum):
    TELEMETRY_TRUNCATED = "telemetry_truncated"
    TRACE_MISSING = "trace_missing"  # artifact arrived, spans never did (Pulse was down)
    TRACE_NOT_APPLICABLE = "trace_not_applicable"  # producer emits no tracing (s2s)
    AUDIO_MISSING = "audio_missing"
    AUDIO_DISABLED = "audio_disabled"  # analysis toggled off for this tenant, not an outage
    ARTIFACT_MISSING = "artifact_missing"
    AUDIO_PARTIAL = "audio_partial"
    PRODUCER_SCHEMA_UNSUPPORTED = "producer_schema_unsupported"
    GATE_TIMEOUT = "gate_timeout"


class SpanEvent(Frozen):
    name: str
    t: float  # seconds from call t0
    attrs: dict = Field(default_factory=dict)
    # Words the producer heard but no turn claimed — overheard, dropped, carried.
    # The discard signal; dropping it hides what STT got wrong.
    content: dict[str, Any] = Field(default_factory=dict)


class Span(Frozen):
    span_id: str
    parent_span_id: str | None
    name: str
    stage: Stage
    t_start: float
    t_end: float | None  # None = never closed (crash mid-turn)
    turn_id: str | None  # nullable by design — the null is discard_rate
    error: bool = False  # OTel span status ERROR / error.type attr / exception event
    attrs: dict = Field(default_factory=dict)  # shape only
    content: dict[str, Any] = Field(default_factory=dict)  # voice.content.* suffix -> text or list
    events: list[SpanEvent] = Field(default_factory=list)


class CallHeader(Frozen):
    call_id: str
    source: str
    environment: str
    started_at: datetime
    engine: str | None = None
    carrier: str | None = None
    stt_provider: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    tts_provider: str | None = None
    voice: str | None = None
    template_sha256: str | None = None
    ended_at: datetime | None = None
    labels: dict = Field(default_factory=dict)  # opaque — the OSS boundary
    counters: dict = Field(default_factory=dict)


class Trace(Frozen):
    header: CallHeader
    spans: list[Span] = Field(default_factory=list)


class AudioRef(Frozen):
    uri: str
    sha256: str
    channels: int
    sample_rate: int
    duration_s: float
    channel_map: dict[int, str]  # carried, never assumed
    t0_offset_s: float | None = None  # audio clock - call clock; may be negative


class Utterance(Frozen):
    channel: str
    t_start: float
    t_end: float


class AudioAnalysis(Frozen):
    utterances: list[Utterance] = Field(default_factory=list)
    peaks: dict[str, bytes] = Field(default_factory=dict)  # channel -> int16 min/max pairs
    energy: dict[str, bytes] = Field(default_factory=dict)  # channel -> LE float32 dBFS/frame
    coverage: dict[str, float] = Field(default_factory=dict)
    quality: dict[str, dict] = Field(default_factory=dict)


class Turn(Frozen):
    """One exchange (caller utterance + agent response). No speaker; opening turns
    have no caller side. Joined to Utterances by time overlap."""

    turn_index: int
    turn_id: str
    trigger: str  # opening | endpoint

    audio_start_s: float | None = None
    audio_end_s: float | None = None

    # span times, offset-corrected onto the audio clock
    stt_final_at: float | None = None
    committed_at: float | None = None
    llm_first_token_at: float | None = None
    tts_start_at: float | None = None
    tts_first_audio_at: float | None = None
    audio_out_start_s: float | None = None
    tts_span_present: bool = False

    # the waterfall
    response_latency_ms: float | None = None
    stt_lag_ms: float | None = None
    endpointing_ms: float | None = None
    llm_ttft_ms: float | None = None
    assembly_ms: float | None = None  # first token -> TTS node opens (~0 for streaming)
    dispatch_ms: float | None = None  # first token -> TTS provider request fires
    tts_ttfb_ms: float | None = None
    playout_ms: float | None = None
    unattributed_ms: float | None = None  # turn duration minus children
    # producer-reported latency (span attribute), when it hands the number directly
    # instead of a first-token/first-audio event. Stored alongside for comparison.
    llm_ttft_reported_ms: float | None = None
    tts_ttfb_reported_ms: float | None = None

    language: str | None = None
    stt_confidence: float | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    tokens_cached: int | None = None
    finish_reason: str | None = None
    tts_chars: int | None = None
    tts_chars_cut: int | None = None
    tts_cancelled: bool = False  # a TTS request was aborted mid-synthesis (speech cut off)
    cut_reason: str | None = None  # barge_in | hangup
    interrupted: bool = False
    interruption_probability: float | None = None  # producer's own confidence (lk.*)
    e2e_latency_ms: float | None = None  # the engine's own end-to-end number, a cross-check
    abandoned: bool = False

    transcript: str | None = None
    llm_raw: str | None = None
    llm_spoken: str | None = None  # from the TTS span, not the LLM span


class MetricValue(Frozen):
    name: str
    value: float | str | None
    samples: list[float] | None = None  # per-turn series
    available: bool = True
    reason: str | None = None


class TrustReport(Frozen):
    reasons: list[TrustReason] = Field(default_factory=list)
    capture_coverage: dict[str, float] = Field(default_factory=dict)
    clock_offset_s: float | None = None
    clock_residual_ms: float | None = None
    clock_residual_per_turn_ms: list[float] | None = None  # signed; +ve trend = ahead-drift
    barge_in_agreement: float | None = None
    layers_run: list[str] = Field(default_factory=list)
    span_dropped_events: int = 0
    unattributed_spans: int = 0


class Analysis(Frozen):
    turns: list[Turn]
    metrics: list[MetricValue]
    trust: TrustReport
    metric_version: int
    adapter_version: int
