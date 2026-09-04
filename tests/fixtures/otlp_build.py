"""Minimal OTLP payload builder for adapter tests (any dialect)."""

from __future__ import annotations

T0 = 1_700_000_000_000_000_000
MS = 1_000_000


def _av(v):
    if isinstance(v, bool):
        return {"boolValue": v}
    if isinstance(v, int):
        return {"intValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    return {"stringValue": str(v)}


def _attrs(d: dict) -> list[dict]:
    return [{"key": k, "value": _av(v)} for k, v in d.items()]


def span(span_id, parent, name, start_ms, end_ms, attrs=None, trace_id="tr1"):
    s = {
        "spanId": span_id, "name": name, "traceId": trace_id,
        "startTimeUnixNano": str(T0 + int(start_ms * MS)),
        "endTimeUnixNano": str(T0 + int(end_ms * MS)),
        "attributes": _attrs(attrs or {}),
    }
    if parent:
        s["parentSpanId"] = parent
    return s


def payload(spans: list[dict], service_name: str = "my-agent") -> dict:
    return {
        "resourceSpans": [{
            "resource": {"attributes": _attrs({"service.name": service_name})},
            "scopeSpans": [{"spans": spans}],
        }]
    }
