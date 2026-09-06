"""Span error capture — OTLP status ERROR / error.type attr / exception event."""

from __future__ import annotations

from voiceobs.frameworks import OTLPAdapter

T = 1_700_000_000_000_000_000


def _span(sid, parent, name, *, status=None, attrs=None, events=None):
    s = {"traceId": "aa" * 16, "spanId": sid, "name": name,
         "startTimeUnixNano": str(T), "endTimeUnixNano": str(T + 1_000_000_000)}
    if parent:
        s["parentSpanId"] = parent
    if status:
        s["status"] = status
    if attrs:
        s["attributes"] = [{"key": k, "value": {"stringValue": str(v)}} for k, v in attrs.items()]
    if events:
        s["events"] = [{"name": n, "timeUnixNano": str(T), "attributes": []} for n in events]
    return s


def _trace(spans):
    payload = {"resourceSpans": [{
        "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "x"}}]},
        "scopeSpans": [{"spans": spans}],
    }]}
    return OTLPAdapter().to_trace(payload)


def test_span_error_detection():
    trace = _trace([
        _span("01" * 8, None, "conversation"),
        _span("02" * 8, "01" * 8, "clean_tool"),
        _span("03" * 8, "01" * 8, "status_err", status={"code": "STATUS_CODE_ERROR", "message": "boom"}),
        _span("04" * 8, "01" * 8, "typed_err", attrs={"error.type": "tool_error"}),
        _span("05" * 8, "01" * 8, "exc_tool", events=["exception"]),
    ])
    by = {s.span_id: s.error for s in trace.spans}
    assert by["02" * 8] is False
    assert by["03" * 8] is True   # span status ERROR
    assert by["04" * 8] is True   # error.type attribute
    assert by["05" * 8] is True   # exception span event
