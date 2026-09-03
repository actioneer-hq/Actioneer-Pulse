"""A producer VO has never heard of must still yield a call and a timeline."""

from __future__ import annotations

from voiceobs.core.model import Stage
from voiceobs.frameworks import OTLPAdapter, adapter_for


def _pipecat() -> dict:
    """Generic OTLP: no voice.* anywhere, names VO does not know."""
    def span(sid, parent, name, start, end):
        s = {"traceId": "aa" * 16, "spanId": sid, "name": name,
             "startTimeUnixNano": str(start), "endTimeUnixNano": str(end)}
        if parent:
            s["parentSpanId"] = parent
        return s

    T = 1_700_000_000_000_000_000
    return {"resourceSpans": [{
        "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "pipecat"}}]},
        "scopeSpans": [{"spans": [
            span("01" * 8, None, "conversation", T, T + 3_000_000_000),
            span("02" * 8, "01" * 8, "stt_service", T, T + 1_000_000_000),
            span("03" * 8, "01" * 8, "llm_service", T + 1_000_000_000, T + 2_000_000_000),
        ]}],
    }]}


def _unknown() -> dict:
    """A producer with no voice.* and names no specific adapter claims."""
    def span(sid, parent, name, start, end):
        s = {"traceId": "aa" * 16, "spanId": sid, "name": name,
             "startTimeUnixNano": str(start), "endTimeUnixNano": str(end)}
        if parent:
            s["parentSpanId"] = parent
        return s

    T = 1_700_000_000_000_000_000
    return {"resourceSpans": [{
        "resource": {"attributes": [{"key": "service.name",
                                     "value": {"stringValue": "someframework"}}]},
        "scopeSpans": [{"spans": [
            span("01" * 8, None, "session", T, T + 3_000_000_000),
            span("02" * 8, "01" * 8, "recognize", T, T + 1_000_000_000),
            span("03" * 8, "01" * 8, "generate", T + 1_000_000_000, T + 2_000_000_000),
        ]}],
    }]}


def test_unknown_producer_still_parses():
    payload = _unknown()
    adapter = adapter_for(payload)
    assert adapter.name == "otlp"

    trace = adapter.to_trace(payload)
    assert trace.header.call_id == "aa" * 16  # no call id to find, so the trace names it
    assert trace.header.source == "someframework"
    assert len(trace.spans) == 3
    # nothing recognised, so nothing is guessed at
    assert {s.stage for s in trace.spans} == {Stage.UNKNOWN}
    assert trace.spans[0].t_start == 0.0


def test_a_new_producer_is_two_dicts():
    """The whole cost of supporting a producer. If this test needs more than names,
    the base has stopped being generic."""

    class PipecatAdapter(OTLPAdapter):
        name = "pipecat"
        service_name = "pipecat"
        stages = {"conversation": Stage.CALL, "stt_service": Stage.STT,  # noqa: RUF012
                  "llm_service": Stage.LLM}

    trace = PipecatAdapter().to_trace(_pipecat())
    assert [s.stage for s in trace.spans] == [Stage.CALL, Stage.STT, Stage.LLM]


def test_turns_without_turn_index_get_distinct_positions():
    """Two turn spans with no turn.index must not collide on one index (the bug that
    crashed the first real LiveKit call: UNIQUE(call_id, turn_index))."""
    from tests.fixtures.otlp_build import payload, span
    from voiceobs.core import join
    from voiceobs.core.model import Stage

    class _A(OTLPAdapter):
        name = "x"
        stages = {"call": Stage.CALL, "turn": Stage.TURN}  # noqa: RUF012

    trace = _A().to_trace(payload([
        span("c", None, "call", 0, 5000),
        span("t1", "c", "turn", 100, 1000),
        span("t2", "c", "turn", 1000, 2000),
    ]))
    turns = join(trace, None).turns
    assert sorted(t.turn_index for t in turns) == [0, 1]
