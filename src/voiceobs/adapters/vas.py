"""VAS adapter — the `voice-cascade` OTLP dialect -> normalized Trace.

Built against vas-contract.md (inventory + schema-v1 queue). Attribute classing is
by prefix at the edge: voice.content.* -> Span.content, an allowlist -> Span.attrs,
everything sensitive dropped."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from voiceobs.adapters.base import UnsupportedSchema
from voiceobs.adapters.otlp import (
    attrs_to_dict,
    iter_spans,
    span_end_ns,
    span_events,
    span_start_ns,
)
from voiceobs.core.model import CallHeader, Span, SpanEvent, Stage, Trace

SERVICE_NAME = "voice-cascade"

_STAGE_BY_NAME: dict[str, Stage] = {
    "voice.call": Stage.CALL,
    "voice.turn": Stage.TURN,
    "stt.finalize": Stage.STT,
    "llm.generate": Stage.LLM,
    "tts.synthesize": Stage.TTS,
    "tool.execute": Stage.TOOL,
    "tool.claim": Stage.TOOL,
    "tool.http": Stage.TOOL,
    "net.connect": Stage.NET,
}

_CONTENT_PREFIX = "voice.content."
_DROP = {
    "transcript", "text", "gen_ai.prompt", "gen_ai.completion",
    "exception.message", "exception.stacktrace",
}


def _keep(key: str) -> bool:
    """Shape allowlist (CONTRACTS.md §7). Content/PII handled separately."""
    if key in _DROP or key.startswith("gen_ai.") and key.endswith(".messages"):
        return False
    if key in ("gen_ai.provider.name", "gen_ai.request.model", "metrics.ttfb"):
        return True
    if key.startswith(_CONTENT_PREFIX):
        return False
    return key.startswith(("gen_ai.usage.", "voice.", "turn.", "lk."))


def _class_attrs(flat: dict[str, Any]) -> tuple[dict, dict[str, str]]:
    """Split a flat attribute dict into (shape attrs, content by suffix)."""
    attrs, content = {}, {}
    for k, v in flat.items():
        if k.startswith(_CONTENT_PREFIX):
            content[k[len(_CONTENT_PREFIX):]] = v
        elif _keep(k):
            attrs[k] = v
    return attrs, content


def _dt(ns: int) -> datetime:
    return datetime.fromtimestamp(ns / 1e9, tz=UTC)


class VASAdapter:
    name = "vas"
    version = 1

    def matches(self, payload: dict) -> bool:
        return any(
            res.get("service.name") == SERVICE_NAME for res, _ in iter_spans(payload)
        )

    def to_trace(self, payload: dict) -> Trace:
        spans_raw = list(iter_spans(payload))
        resource = spans_raw[0][0] if spans_raw else {}
        if int(resource.get("voice.schema_version") or 0) < 1:
            raise UnsupportedSchema("voice-cascade requires schema_version >= 1")

        root = self._root(spans_raw)
        t0 = span_start_ns(root)

        spans = [self._span(s, t0) for _, s in spans_raw]
        spans.sort(key=lambda s: s.t_start)
        return Trace(header=self._header(root, resource), spans=spans)

    def _root(self, spans_raw: list[tuple[dict, dict]]) -> dict:
        for _, s in spans_raw:
            if s.get("name") == "voice.call":
                return s
        raise ValueError("no voice.call root span in payload")

    def _span(self, s: dict, t0: int) -> Span:
        flat = attrs_to_dict(s.get("attributes"))
        attrs, content = _class_attrs(flat)
        end = span_end_ns(s)
        return Span(
            span_id=s["spanId"],
            parent_span_id=s.get("parentSpanId") or None,
            name=s["name"],
            stage=_STAGE_BY_NAME.get(s["name"], Stage.NET),
            t_start=round((span_start_ns(s) - t0) / 1e9, 6),
            t_end=round((end - t0) / 1e9, 6) if end is not None else None,
            turn_id=flat.get("voice.turn_id"),
            attrs=attrs,
            content=content,
            events=[self._event(e, t0) for e in span_events(s)],
        )

    def _event(self, ev: tuple[str, int, dict], t0: int) -> SpanEvent:
        name, ts, flat = ev
        attrs, _ = _class_attrs(flat)
        return SpanEvent(name=name, t=round((ts - t0) / 1e9, 6), attrs=attrs)

    def _header(self, root: dict, resource: dict) -> CallHeader:
        r = attrs_to_dict(root.get("attributes"))
        end = span_end_ns(root)
        return CallHeader(
            call_id=r["voice.call_id"],
            source=resource.get("service.name", SERVICE_NAME),
            environment=resource.get("deployment.environment", "prod"),
            started_at=_dt(span_start_ns(root)),
            ended_at=_dt(end) if end is not None else None,
            engine=r.get("voice.engine"),
            carrier=r.get("voice.carrier"),
            stt_provider=r.get("voice.stt.provider") or r.get("gen_ai.provider.name"),
            llm_provider=r.get("voice.llm.provider"),
            tts_provider=r.get("voice.tts.provider"),
            voice=r.get("voice.tts_voice") or r.get("voice.voice"),
            template_sha256=r.get("voice.prompt.template_sha256"),
            llm_model=None,  # VAS has no model field; the provider string embeds it
            labels=_labels(r),
            counters=_counters(r),
        )


def _labels(r: dict[str, Any]) -> dict:
    return {
        k: r[f"voice.{k}"]
        for k in ("tenant_id", "campaign_id")
        if r.get(f"voice.{k}") is not None
    }


def _counters(r: dict[str, Any]) -> dict:
    keys = {
        "stt_segments_heard": "voice.stt.segments_heard",
        "stt_segments_overheard": "voice.stt.segments_overheard",
        "stt_segments_dropped": "voice.stt.segments_dropped",
        "turns": "voice.turns",
    }
    return {out: r[src] for out, src in keys.items() if r.get(src) is not None}
