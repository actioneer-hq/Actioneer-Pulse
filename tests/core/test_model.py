"""Type-level tests for core/model.py and core/config.py.

These assert the baked-in decisions from CONTRACTS.md §5 hold structurally:
frozen types, nullable-by-design fields, shape/content kept apart.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from voiceobs.core import (
    METRIC_DEFS_BY_NAME,
    Analysis,
    AudioRef,
    CallHeader,
    MetricConfig,
    MetricValue,
    Span,
    SpanEvent,
    Stage,
    Trace,
    TrustReason,
    TrustReport,
    Turn,
    Utterance,
)


def _now() -> datetime:
    return datetime(2026, 8, 20, tzinfo=UTC)


def test_span_nullable_by_design():
    # t_end None = crash mid-turn (data); turn_id None = the discard_rate null.
    s = Span(
        span_id="s1", parent_span_id=None, name="voice.call",
        stage=Stage.CALL, t_start=0.0, t_end=None, turn_id=None,
    )
    assert s.t_end is None
    assert s.turn_id is None
    assert s.parent_span_id is None  # None parent = root


def test_span_shape_and_content_kept_apart():
    s = Span(
        span_id="s2", parent_span_id="s1", name="stt.finalize",
        stage=Stage.STT, t_start=1.0, t_end=1.5, turn_id="c:1",
        attrs={"voice.stt_confidence": 0.67},
        content={"transcript": "haan ji"},
    )
    # content text must never leak into attrs (shape only)
    assert "transcript" not in s.attrs
    assert s.content["transcript"] == "haan ji"


def test_frozen_types_are_immutable():
    s = SpanEvent(name="llm.first_token", t=2.0)
    with pytest.raises(ValidationError):  # pydantic raises on frozen mutation
        s.t = 3.0  # type: ignore[misc]


def test_audioref_t0_offset_may_be_negative_and_none():
    ref = AudioRef(
        uri="gs://b/k", sha256="x", channels=2, sample_rate=8000,
        duration_s=56.18, channel_map={0: "caller", 1: "agent"},
        t0_offset_s=-0.412,
    )
    assert ref.t0_offset_s == -0.412
    assert ref.channel_map[0] == "caller"  # carried, never assumed

    ref2 = ref.model_copy(update={"t0_offset_s": None})
    assert ref2.t0_offset_s is None


def test_metricvalue_available_and_reason():
    mv = MetricValue(name="barge_in", value=None, available=False, reason="mono")
    assert mv.available is False
    assert mv.reason == "mono"


def test_trust_residual_series_is_signed_list():
    tr = TrustReport(
        reasons=[TrustReason.AUDIO_PARTIAL],
        capture_coverage={"caller": 0.90, "agent": 0.47},
        clock_residual_per_turn_ms=[5.0, 12.0, 20.0, 31.0],  # monotonic +ve = ahead-drift
    )
    assert tr.clock_residual_per_turn_ms == [5.0, 12.0, 20.0, 31.0]
    assert TrustReason.AUDIO_PARTIAL in tr.reasons


def test_minimal_analysis_constructs():
    trace = Trace(header=CallHeader(
        call_id="c", source="livekit", environment="prod", started_at=_now(),
    ))
    assert trace.spans == []
    turn = Turn(turn_index=0, turn_id="c:0", trigger="opening")
    analysis = Analysis(
        turns=[turn], metrics=[], trust=TrustReport(),
        metric_version=1, adapter_version=1,
    )
    assert analysis.turns[0].turn_id == "c:0"
    # opening turn has no caller side
    assert analysis.turns[0].audio_start_s is None


def test_evidence_is_nullable_identity_is_not():
    """The boundary principle: identity is synthesizable, evidence is nullable.
    A bare-transcript producer maps dialogue to spans with no clock at all."""
    s = Span(
        span_id="f3ab-0",  # mapper-minted — identity is bookkeeping, not evidence
        parent_span_id=None, name="line", stage=Stage.STT,
        sequence=0, content={"transcript": "hello"},
    )
    assert s.t_start is None and s.t_end is None  # producer never had a clock
    assert s.sequence == 0  # source order still known
    assert s.content["transcript"] == "hello"

    header = CallHeader(call_id="c", source="storage", environment="prod")
    assert header.started_at is None  # no wall clock logged — null, never invented
    trace = Trace(header=header, spans=[s])
    assert trace.spans[0].stage is Stage.STT

    with pytest.raises(ValidationError):  # identity can never be null
        Span(span_id=None, parent_span_id=None, name="x", stage=Stage.STT)  # type: ignore[arg-type]


def test_untimed_span_event_carries_content():
    e = SpanEvent(name="stt.segment", content={"overheard": "wait, that's not me"})
    assert e.t is None  # instant marker without a clock still carries its evidence


def test_utterance_has_speaker():
    u = Utterance(channel="caller", t_start=0.0, t_end=1.2)
    assert u.channel == "caller"


def test_metric_config_documented_defaults():
    cfg = MetricConfig()
    assert cfg.vad_threshold_dbfs == -50.0
    assert cfg.turn_gap_s == 1.2
    assert cfg.dead_air_min_s == 1.5
    assert cfg.echo_gain_min == 0.05
    assert cfg.peaks_per_second == 50


def test_metric_defs_registry_covers_key_metrics():
    for name in ("capture_coverage", "response_latency_ms", "barge_in", "llm_ttft_ms"):
        assert name in METRIC_DEFS_BY_NAME
    assert METRIC_DEFS_BY_NAME["capture_coverage"].higher_is_better is True
