"""Hand-authored ExportTraceServiceRequest for a single LiveKit Agents call.

The generic "a call arrived over OTLP" fixture for the suite. Shaped like a real LiveKit
trace so it routes to LiveKitAdapter and yields metrics: an `agent_session` root, a
`user_turn` + sibling `agent_turn`, `user_speaking`/`eou_detection`, and `llm_request`/
`tts_request` carrying the `lk.llm_metrics`/`lk.tts_metrics` JSON-string blobs.

It also carries the canonical, cross-producer ingest hints `voice.call_id` / `voice.tenant_id`
on the ROOT span (only) and `voice.schema_version` on the resource. Those are read by the
ingest layer (before any adapter) — LiveKit itself doesn't emit them — so this call keeps a
stable external id ("c1") and tenant ("vastu-hfc") for identity-focused tests. Stripping the
root (see tests' `_children_only`) removes the call_id, exactly as a pre-close batch would.

Times are epoch ns; offsets below are ms from the call start T0."""

from __future__ import annotations

import json

T0 = 1_700_000_000_000_000_000  # call start, epoch ns
MS = 1_000_000


def _av(v):
    if isinstance(v, list):
        return {"arrayValue": {"values": [_av(x) for x in v]}}
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


TRACE_ID = "c1c1" * 8  # every real OTLP span carries one; the fixture must too


def _span(span_id, parent, name, start_ms, end_ms, attrs, events=None):
    s = {
        "traceId": TRACE_ID,
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


def sample_call(service_name: str = "livekit", schema_version: int = 1) -> dict:
    resource_attrs = {
        "service.name": service_name,
        "deployment.environment": "prod",
        "voice.schema_version": schema_version,
        "voice.role": "worker",
    }

    # Root: agent_session. Carries the canonical ingest hints (call_id + tenant) — on the
    # ROOT ONLY, mirroring how a producer stamps identity on the span that closes the call.
    session = _span(
        "sess", None, "agent_session", 0, 3000,
        {
            "voice.call_id": "c1",
            "voice.tenant_id": "vastu-hfc",
            "voice.campaign_id": "camp-1",
        },
    )
    # Caller half.
    user_turn = _span(
        "ut", "sess", "user_turn", 900, 1100,
        {
            "turn.index": 1,
            "lk.interrupted": False,
            "lk.end_of_turn_delay": 0.4,          # endpointing hold (s)
            "lk.pii.user_transcript": "haan ji",  # -> content transcript
        },
    )
    user_speaking = _span(
        "spk", "ut", "user_speaking", 500, 1000, {},  # end = real end of speech
    )
    eou = _span(
        "eou", "ut", "eou_detection", 900, 1000,
        {"lk.transcript_confidence": 0.67},
    )
    # Agent half — a sibling of user_turn; the adapter folds it into the same exchange.
    agent_turn = _span(
        "at", "sess", "agent_turn", 1100, 2200,
        {
            "lk.interrupted": False,
            "lk.pii.response.text": "haan ji, boliye",  # -> content llm_spoken
        },
    )
    llm = _span(
        "lreq", "at", "llm_request", 1100, 1900,
        {
            "lk.llm_metrics": json.dumps({
                "ttft": 0.3, "completion_tokens": 42, "prompt_tokens": 50,
                "prompt_cached_tokens": 8, "total_tokens": 92, "tokens_per_second": 18.3,
                "metadata": {"model_name": "gpt-x"},
            }),
        },
        events=[("llm.first_token", 1400, {})],  # exercised by test_otlp span-events parsing
    )
    tts = _span(
        "treq", "at", "tts_request", 1500, 2200,
        {
            "lk.tts_metrics": json.dumps({
                "ttfb": 0.2, "characters_count": 100, "audio_duration": 3.19,
                "streamed": False, "metadata": {"model_name": "sarvam-tts"},
            }),
        },
    )
    playout = _span("play", "at", "agent_speaking", 1700, 2200, {})

    return {
        "resourceSpans": [
            {
                "resource": {"attributes": _attrs(resource_attrs)},
                "scopeSpans": [{"spans": [
                    session, user_turn, user_speaking, eou, agent_turn, llm, tts, playout,
                ]}],
            }
        ]
    }
