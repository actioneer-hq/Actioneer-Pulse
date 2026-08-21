"""Hand-authored ExportTraceServiceRequest for a single voice-cascade call.

One opening + one endpoint turn with the span/event shapes from vas-contract.md,
plus a voice.content.transcript (routed to content) and a gen_ai.prompt (dropped).
Times are epoch ns; offsets below are ms from the call start T0."""

from __future__ import annotations

T0 = 1_700_000_000_000_000_000  # call start, epoch ns
MS = 1_000_000


def _av(v):
    if isinstance(v, bool):
        return {"boolValue": v}
    if isinstance(v, int):
        return {"intValue": str(v)}  # OTLP encodes int64 as string
    if isinstance(v, float):
        return {"doubleValue": v}
    return {"stringValue": str(v)}


def _attrs(d: dict) -> list[dict]:
    return [{"key": k, "value": _av(v)} for k, v in d.items()]


def _ns(ms: float) -> str:
    return str(T0 + int(ms * MS))


def _span(span_id, parent, name, start_ms, end_ms, attrs, events=None):
    s = {
        "spanId": span_id,
        "name": name,
        "startTimeUnixNano": _ns(start_ms),
        "endTimeUnixNano": _ns(end_ms),
        "attributes": _attrs(attrs),
    }
    if parent:
        s["parentSpanId"] = parent
    if events:
        s["events"] = [
            {"name": n, "timeUnixNano": _ns(t), "attributes": _attrs(a)}
            for n, t, a in events
        ]
    return s


def sample_call(service_name: str = "voice-cascade", schema_version: int = 1) -> dict:
    resource_attrs = {
        "service.name": service_name,
        "deployment.environment": "prod",
        "voice.schema_version": schema_version,
        "voice.role": "worker",
    }

    call = _span(
        "call", None, "voice.call", 0, 3000,
        {
            "voice.call_id": "c1",
            "voice.engine": "cascade",
            "voice.carrier": "plivo",
            "voice.stt.provider": "sarvam-stt",
            "voice.llm.provider": "gpt-x",
            "voice.tts.provider": "sarvam-tts",
            "voice.tenant_id": "vastu-hfc",
            "voice.campaign_id": "camp-1",
            "voice.prompt.template_sha256": "a" * 64,
            "voice.turns": 1,
            "voice.stt.segments_heard": 3,
        },
        events=[
            ("turn.committed", 1100, {}),
            ("stt.segment", 900, {"voice.chars": 7, "voice.final": True}),
        ],
    )
    turn = _span(
        "t1", "call", "voice.turn", 900, 2200,
        {
            "voice.turn_id": "c1:1",
            "voice.turn.index": 1,
            "voice.turn.trigger": "endpoint",
            "voice.interrupted": False,
        },
    )
    stt = _span(
        "stt", "t1", "stt.finalize", 600, 1000,
        {
            "voice.turn_id": "c1:1",
            "voice.stt_confidence": 0.67,
            "voice.stt_language": "hi-IN",
            "voice.content.transcript": "haan ji",  # -> content
            "gen_ai.prompt": "SYSTEM PROMPT LEAK",  # -> dropped
        },
    )
    llm = _span(
        "llm", "t1", "llm.generate", 1100, 1900,
        {
            "voice.turn_id": "c1:1",
            "gen_ai.provider.name": "gpt-x",
            "gen_ai.usage.output_tokens": 42,
            "voice.content.llm_raw": "haan ji, boliye",  # -> content
        },
        events=[("llm.first_token", 1400, {})],
    )
    tts = _span(
        "tts", "t1", "tts.synthesize", 1500, 2200,
        {
            "voice.turn_id": "c1:1",
            "voice.tts_chars": 100,
            "voice.tts_chars_cut": 16,
            "voice.tts_cut_reason": "barge_in",
            "voice.tts_voice": "meera",
            "voice.content.llm_spoken": "haan ji",  # -> content
        },
        events=[("tts.first_audio", 1700, {})],
    )

    return {
        "resourceSpans": [
            {
                "resource": {"attributes": _attrs(resource_attrs)},
                "scopeSpans": [{"spans": [call, turn, stt, llm, tts]}],
            }
        ]
    }
