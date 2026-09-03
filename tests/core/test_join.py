"""join() invariants: unattributed = uncovered wall-clock (interval union, never negative),
clock anchoring, signed residual, and every missing-evidence path -> the right TrustReason."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from voiceobs.core.join import join
from voiceobs.core.model import (
    AudioAnalysis,
    CallHeader,
    Span,
    SpanEvent,
    Stage,
    Trace,
    TrustReason,
    Utterance,
)


def _header(engine="cascade", **kw) -> CallHeader:
    return CallHeader(
        call_id="c1", source="voice-cascade", environment="prod",
        started_at=datetime(2026, 8, 20, tzinfo=UTC), engine=engine, **kw,
    )


def _span(span_id, parent, name, stage, t0, t1, turn_id, **kw) -> Span:
    return Span(span_id=span_id, parent_span_id=parent, name=name, stage=stage,
                t_start=t0, t_end=t1, turn_id=turn_id, **kw)


def _cascade_trace() -> Trace:
    # One endpoint turn. Call clock. STT final 1.0, committed 1.1, llm start 1.1,
    # first token 1.4, tts start 1.5, first audio 1.7. turn window [0.9, 2.2].
    turn = _span("t1", "call", "voice.turn", Stage.TURN, 0.9, 2.2, "c1:1",
                 attrs={"turn.index": 1, "turn.trigger": "endpoint"})
    stt = _span("s-stt", "t1", "stt.finalize", Stage.STT, 0.6, 1.0, "c1:1",
                attrs={"stt.confidence": 0.67, "stt.language": "hi-IN"})
    llm = _span("s-llm", "t1", "llm.generate", Stage.LLM, 1.1, 1.9, "c1:1",
                attrs={"gen_ai.usage.output_tokens": 42},
                events=[SpanEvent(name="llm.first_token", t=1.4)])
    tts = _span("s-tts", "t1", "tts.synthesize", Stage.TTS, 1.5, 2.2, "c1:1",
                attrs={"tts.chars": 100, "tts.chars_cut": 16,
                       "tts.cut_reason": "barge_in"},
                events=[SpanEvent(name="tts.first_audio", t=1.7)])
    call = _span("call", None, "voice.call", Stage.CALL, 0.0, 3.0, None,
                 events=[SpanEvent(name="turn.committed", t=1.1)])
    return Trace(header=_header(), spans=[call, turn, stt, llm, tts])


def _audio(offset_applied: float) -> AudioAnalysis:
    # Audio clock. Caller speaks up to (1.0 - offset); agent audio out at (1.7 - offset).
    caller_end = 1.0 - offset_applied
    agent_start = 1.7 - offset_applied
    return AudioAnalysis(
        utterances=[
            Utterance(channel="caller", t_start=0.2, t_end=caller_end),
            Utterance(channel="agent", t_start=agent_start, t_end=2.4 - offset_applied),
        ],
        coverage={"caller": 0.90, "agent": 0.88},
    )


def test_unattributed_is_the_uncovered_gap():
    off = 0.5
    analysis = join(_cascade_trace(), _audio(off), t0_offset_s=off)
    assert len(analysis.turns) == 1
    t = analysis.turns[0]
    assert t.response_latency_ms is not None
    assert t.unattributed_ms is not None and t.unattributed_ms >= 0  # never negative
    # v2v window is [stt_final=1.0, first_audio=1.7]; the LLM/TTS spans cover [1.1, 1.7],
    # so the only uncovered wall-clock is the 0.1s gap between STT finishing and LLM start.
    assert abs(t.unattributed_ms - 100) < 1


def test_anchor_shifts_span_times_onto_audio_clock():
    off = 0.5
    t = join(_cascade_trace(), _audio(off), t0_offset_s=off).turns[0]
    # llm.first_token at call-time 1.4 -> audio-time 0.9
    assert abs(t.llm_first_token_at - (1.4 - off)) < 1e-6
    # tts first audio at call-time 1.7 -> audio-time 1.2
    assert abs(t.tts_first_audio_at - (1.7 - off)) < 1e-6


def test_zero_offset_when_coclocked():
    t = join(_cascade_trace(), _audio(0.0), t0_offset_s=None).turns[0]
    assert abs(t.tts_first_audio_at - 1.7) < 1e-6


def test_layer2_metrics_emitted():
    analysis = join(_cascade_trace(), _audio(0.0), t0_offset_s=0.0)
    names = {m.name for m in analysis.metrics}
    assert {"llm_ttft_ms", "assembly_ms", "tts_ttfb_ms", "truncation_rate",
            "cut_reason", "tokens_per_turn", "capture_coverage"} <= names
    trunc = next(m for m in analysis.metrics if m.name == "truncation_rate")
    assert abs(trunc.value - 0.16) < 1e-6  # 16/100
    cut = next(m for m in analysis.metrics if m.name == "cut_reason")
    assert cut.value == "barge_in"


def test_clock_residual_series_is_signed_and_per_turn():
    analysis = join(_cascade_trace(), _audio(0.0), t0_offset_s=0.0)
    res = analysis.trust.clock_residual_per_turn_ms
    assert res is not None and len(res) == 1
    # span first-audio (1.7) vs audio agent start (1.7) -> ~0 residual here
    assert abs(res[0]) < 1.0


def test_audio_missing_degrades_to_events_only():
    analysis = join(_cascade_trace(), None)
    assert "audio" not in analysis.trust.layers_run
    assert "events" in analysis.trust.layers_run
    assert TrustReason.AUDIO_MISSING in analysis.trust.reasons
    # still produces turns from spans
    assert len(analysis.turns) == 1


def test_cascade_without_spans_is_trace_missing():
    trace = Trace(header=_header(engine="cascade"), spans=[])
    analysis = join(trace, _audio(0.0), t0_offset_s=0.0)
    assert TrustReason.TRACE_MISSING in analysis.trust.reasons
    assert analysis.turns == []


def test_s2s_without_spans_is_not_applicable_not_outage():
    trace = Trace(header=_header(engine="s2s"), spans=[])
    analysis = join(trace, _audio(0.0), t0_offset_s=0.0)
    assert TrustReason.TRACE_NOT_APPLICABLE in analysis.trust.reasons
    assert TrustReason.TRACE_MISSING not in analysis.trust.reasons


def test_low_coverage_flags_audio_partial():
    analysis = join(
        _cascade_trace(),
        AudioAnalysis(utterances=[], coverage={"caller": 0.40, "agent": 0.88}),
        t0_offset_s=0.0,
    )
    assert TrustReason.AUDIO_PARTIAL in analysis.trust.reasons


def test_dropped_events_flag_telemetry_truncated():
    trace = _cascade_trace()
    hdr = trace.header
    trace = Trace(
        header=CallHeader(
            call_id=hdr.call_id, source=hdr.source, environment=hdr.environment,
            started_at=hdr.started_at, engine=hdr.engine,
            counters={"span_dropped_events": 3},
        ),
        spans=trace.spans,
    )
    analysis = join(trace, _audio(0.0), t0_offset_s=0.0)
    assert TrustReason.TELEMETRY_TRUNCATED in analysis.trust.reasons
    assert analysis.trust.span_dropped_events == 3


def test_response_latency_is_span_side_not_audio():
    # caller stop (stt end) = 1.0, tts first audio = 1.7 -> 700ms, from spans.
    # Give the audio a DELIBERATELY wrong agent onset; the number must ignore it.
    audio = AudioAnalysis(
        utterances=[
            Utterance(channel="caller", t_start=0.2, t_end=1.0),
            Utterance(channel="agent", t_start=2.9, t_end=3.0),  # nowhere near 1.7
        ],
        coverage={"caller": 0.9, "agent": 0.9},
    )
    t = join(_cascade_trace(), audio, t0_offset_s=0.0).turns[0]
    assert t.response_latency_ms == pytest.approx(700.0)  # 1.7 - 1.0, span-derived


def test_agent_talk_ratio_from_spans():
    # agent TTS span window = [1.5, 2.2] = 0.7s; duration = last audio end (2.4s).
    # The value comes from the SPAN window, not agent VAD.
    analysis = join(_cascade_trace(), _audio(0.0), t0_offset_s=0.0)
    agent = next(m for m in analysis.metrics if m.name == "talk_ratio_agent")
    assert agent.value == pytest.approx(0.7 / 2.4, abs=0.02)


def test_agent_metrics_unavailable_without_agent_spans():
    # a turn with STT/LLM but no TTS/PLAYOUT span -> no agent window
    turn = _span("t1", "call", "voice.turn", Stage.TURN, 0.9, 2.0, "c1:1",
                 attrs={"turn.index": 1})
    stt = _span("s-stt", "t1", "stt.finalize", Stage.STT, 0.6, 1.0, "c1:1", attrs={})
    call = _span("call", None, "voice.call", Stage.CALL, 0.0, 3.0, None)
    trace = Trace(header=_header(), spans=[call, turn, stt])
    analysis = join(trace, _audio(0.0), t0_offset_s=0.0)
    bi = next(m for m in analysis.metrics if m.name == "barge_in")
    assert bi.available is False and bi.reason == "no agent spans"


def test_reported_latency_stored_alongside_event_derived():
    # LLM span carries a reported metrics.ttft (seconds); TTS carries metrics.ttfb.
    spans = []
    for s in _cascade_trace().spans:
        if s.stage is Stage.LLM:
            s = s.model_copy(update={"attrs": {**s.attrs, "metrics.ttft": 0.3}})
        if s.stage is Stage.TTS:
            s = s.model_copy(update={"attrs": {**s.attrs, "metrics.ttfb": 0.12}})
        spans.append(s)
    t = join(Trace(header=_header(), spans=spans), _audio(0.0), t0_offset_s=0.0).turns[0]
    # event-derived value still computed (from llm.first_token), and reported stored too
    assert t.llm_ttft_ms is not None
    assert t.llm_ttft_reported_ms == pytest.approx(300.0)   # 0.3s -> ms
    assert t.tts_ttfb_reported_ms == pytest.approx(120.0)


def test_transcript_and_confidence_flow_from_spans():
    trace = _cascade_trace()
    # attach content to the stt span
    spans = []
    for s in trace.spans:
        if s.stage is Stage.STT:
            s = s.model_copy(update={"content": {"transcript": "haan ji"}})
        spans.append(s)
    analysis = join(Trace(header=trace.header, spans=spans), _audio(0.0), t0_offset_s=0.0)
    t = analysis.turns[0]
    assert t.transcript == "haan ji"
    assert abs(t.stt_confidence - 0.67) < 1e-6
    assert t.language == "hi-IN"
    assert t.tokens_out == 42
