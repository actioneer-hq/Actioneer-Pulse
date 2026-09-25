"""OTLP/HTTP helpers, dialect-agnostic. Every producer's adapter reuses these.

OTLP JSON is camelCase and boxes each attribute value in an AnyValue wrapper. The
protobuf wire format maps to the same shape, so `decode_protobuf` is the only place
that needs to know which one arrived."""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from typing import Any

from voiceobs.config import get_config
from voiceobs.util import bounded_gunzip

Scalar = str | int | float | bool | None


def decode_otlp(raw: bytes, *, filename: str = "") -> dict:
    """Decode an OTLP export from a stored file (gzip-aware, JSON or protobuf) into the OTLP/JSON dict
    shape. Used by OTLP-from-blob backfill, where there's no content-type — infer from the gzip magic
    and the file extension, falling back to try-JSON-then-protobuf for unknown names."""
    if raw[:2] == b"\x1f\x8b":  # gzip magic — bound the output (a stored file can be a gzip bomb)
        raw = bounded_gunzip(raw, get_config().max_decoded_bytes)
    name = filename.lower()
    if name.endswith((".pb", ".protobuf", ".bin")):
        return decode_protobuf(raw)
    if name.endswith(".json"):
        return json.loads(raw)
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return decode_protobuf(raw)


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


# Ids are `bytes` on the wire and JSON-map to base64; everything downstream — and every
# id already stored — is hex.
_ID_KEYS = ("traceId", "spanId", "parentSpanId")


def decode_protobuf(body: bytes) -> dict:
    """OTLP/protobuf -> the dict shape OTLP/JSON produces.

    Real producers send protobuf: `OTLPSpanExporter` has no JSON mode. Rejecting it
    would reject every batch that isn't a hand-written test fixture."""
    from google.protobuf.json_format import MessageToDict
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
        ExportTraceServiceRequest,
    )

    msg = ExportTraceServiceRequest()
    msg.ParseFromString(body)
    payload = MessageToDict(msg)
    for rs in payload.get("resourceSpans", []):
        for scope in rs.get("scopeSpans", []):
            for span in scope.get("spans", []):
                _hexify(span)
                for link in span.get("links", []):
                    _hexify(link)
    return payload


def _hexify(d: dict) -> None:
    """base64 id -> hex, in place. Skipping this breaks parent links silently."""
    for k in _ID_KEYS:
        if d.get(k):
            d[k] = base64.b64decode(d[k]).hex()
