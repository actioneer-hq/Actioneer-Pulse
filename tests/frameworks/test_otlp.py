"""OTLP helper tests — unboxing, flattening, span iteration."""

from __future__ import annotations

from tests.fixtures.livekit_call import sample_call
from voiceobs.frameworks import otlp


def test_unwrap_each_value_kind():
    assert otlp.unwrap({"stringValue": "x"}) == "x"
    assert otlp.unwrap({"intValue": "42"}) == 42  # int64 encoded as string
    assert otlp.unwrap({"doubleValue": 0.5}) == 0.5
    assert otlp.unwrap({"boolValue": False}) is False
    assert otlp.unwrap({}) is None


def test_attrs_to_dict_flattens():
    d = otlp.attrs_to_dict([
        {"key": "a", "value": {"stringValue": "s"}},
        {"key": "n", "value": {"intValue": "3"}},
    ])
    assert d == {"a": "s", "n": 3}


def test_iter_spans_carries_resource():
    rows = list(otlp.iter_spans(sample_call()))
    assert len(rows) == 8
    res, span = rows[0]
    assert res["service.name"] == "livekit"
    assert res["voice.schema_version"] == 1
    assert "name" in span


def test_span_events_parsed():
    _, llm = next(
        (r, s) for r, s in otlp.iter_spans(sample_call()) if s["name"] == "llm_request"
    )
    events = otlp.span_events(llm)
    assert events[0][0] == "llm.first_token"
    assert events[0][1] > 0
