"""OTLP/HTTP JSON helpers, dialect-agnostic. Every producer's adapter reuses these.

OTLP JSON is camelCase and boxes each attribute value in an AnyValue wrapper."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

Scalar = str | int | float | bool | None


def unwrap(anyvalue: dict) -> Scalar | list | dict:
    """Unbox one OTLP AnyValue ({stringValue|intValue|doubleValue|boolValue|...})."""
    if not anyvalue:
        return None
    if "stringValue" in anyvalue:
        return anyvalue["stringValue"]
    if "boolValue" in anyvalue:
        return anyvalue["boolValue"]
    if "intValue" in anyvalue:
        return int(anyvalue["intValue"])  # OTLP sends int64 as a string
    if "doubleValue" in anyvalue:
        return float(anyvalue["doubleValue"])
    if "arrayValue" in anyvalue:
        return [unwrap(v) for v in anyvalue["arrayValue"].get("values", [])]
    if "kvlistValue" in anyvalue:
        return attrs_to_dict(anyvalue["kvlistValue"].get("values", []))
    return None


def attrs_to_dict(attributes: list[dict] | None) -> dict[str, Any]:
    """Flatten an OTLP attribute list to {key: python_value}."""
    return {a["key"]: unwrap(a.get("value", {})) for a in (attributes or [])}


def iter_spans(payload: dict) -> Iterator[tuple[dict[str, Any], dict]]:
    """Yield (resource_attrs, span_json) for every span, carrying resource context."""
    for rs in payload.get("resourceSpans", []):
        resource_attrs = attrs_to_dict(rs.get("resource", {}).get("attributes"))
        for scope in rs.get("scopeSpans", []):
            for span in scope.get("spans", []):
                yield resource_attrs, span


def span_start_ns(span: dict) -> int:
    return int(span["startTimeUnixNano"])


def span_end_ns(span: dict) -> int | None:
    end = span.get("endTimeUnixNano")
    return int(end) if end else None


def span_events(span: dict) -> list[tuple[str, int, dict[str, Any]]]:
    """(name, timeUnixNano, attrs) for each span event."""
    return [
        (e["name"], int(e["timeUnixNano"]), attrs_to_dict(e.get("attributes")))
        for e in span.get("events", [])
    ]
