"""One OTLP dialect -> Trace. The base handles any producer; a subclass adds names.

Writing an adapter (LiveKit, your own) is two dicts:

    class MyAdapter(OTLPAdapter):
        name = "myframework"
        service_name = "myframework"
        stages = {"stt_service": Stage.STT, "llm_service": Stage.LLM}
        attr_aliases = {"myframework.turn": "turn.id"}

Everything else — the span tree, timings, content splitting, PII dropping — is the
same for every producer, because it is OTLP, not dialect.

`attr_aliases` maps a producer's names onto Pulse's canonical vocabulary, which is the
only thing `core/join.py` reads:

    turn.id  turn.index  turn.trigger  turn.interrupted  turn.abandoned
    stt.language  stt.confidence  llm.finish_reason
    tts.chars  tts.chars_cut  tts.cut_reason
    gen_ai.usage.input_tokens  gen_ai.usage.output_tokens   (OTel GenAI, not ours)

Unmapped attributes still reach `Span.attrs`; they are just not read by the waterfall.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

from voiceobs.core.model import CallHeader, Span, SpanEvent, Stage, Trace
from voiceobs.frameworks.base import UnsupportedSchema
from voiceobs.frameworks.otlp import (
    attrs_to_dict,
    iter_spans,
    span_end_ns,
    span_events,
    span_start_ns,
)

# Nothing is dropped: Pulse is the place you go to see what actually happened, and an
# observability tool that hides the conversation cannot explain the call. Erasure is
# per call (DELETE /v1/calls/{id}), not per attribute.
_DROP: set[str] = set()


def _dt(ns: int) -> datetime:
    return datetime.fromtimestamp(ns / 1e9, tz=UTC)


def _span_errored(s: dict, raw: dict, events: list) -> bool:
    """Did this span fail? OTel marks it via span status ERROR, an `error.type` attribute
    (LiveKit sets error.type="tool_error"), or an `exception` span event."""
    code = str((s.get("status") or {}).get("code") or "").upper()
    if "ERROR" in code:
        return True
    if raw.get("error.type") is not None:
        return True
    return any(name == "exception" for name, _, _ in events)


def _propagate_turn_ids(spans: list[Span]) -> list[Span]:
    """Attach each span to its turn. Some producers stamp turn.id on every span; others
    (LiveKit) instead nest a turn's STT/LLM/TTS spans UNDER the turn span, so a child's turn
    is its nearest turn-stage ancestor. Only fills a missing turn_id — never overrides one
    the producer set. A turn span's own id becomes its turn_id so children can match it."""
    by_id = {s.span_id: s for s in spans}

    def turn_of(s: Span) -> str | None:
        cur: Span | None = s
        seen: set[str] = set()
        while cur is not None and cur.span_id not in seen:
            seen.add(cur.span_id)
            if cur.stage is Stage.TURN:
                return cur.turn_id or cur.span_id
            cur = by_id.get(cur.parent_span_id) if cur.parent_span_id else None
        return None

    out: list[Span] = []
    for s in spans:
        if s.turn_id is None:
            tid = turn_of(s)
            if tid is not None:
                s = s.model_copy(update={"turn_id": tid})
        out.append(s)
    return out


class OTLPAdapter:
    name = "otlp"
    version = 1

    service_name: str | None = None  # None = match any producer
    stages: ClassVar[dict[str, Stage]] = {}
    attr_aliases: ClassVar[dict[str, str]] = {}
    content_prefix = "voice.content."
    content_keys: ClassVar[dict[Stage, dict[str, str]]] = {}
    # Producer attributes that ARE content, not shape: {producer_attr_key: content_kind}.
    # For producers (LiveKit) that carry the transcript as a plain attribute instead of
    # under content_prefix. Routed to Span.content, not Span.attrs.
    content_attrs: ClassVar[dict[str, str]] = {}
    # Set to narrow Span.attrs to an allowlist. None (default) keeps everything.
    keep_prefixes: tuple[str, ...] | None = None

    def matches(self, payload: dict) -> bool:
        if self.service_name is None:
            return True
        return any(
            res.get("service.name") == self.service_name for res, _ in iter_spans(payload)
        )

    def to_trace(self, payload: dict) -> Trace:
        rows = list(iter_spans(payload))
        resource = rows[0][0] if rows else {}
        self.check_schema(resource)

        root = next((s for _, s in rows if not s.get("parentSpanId")), None)
        if root is None:
            raise UnsupportedSchema("no root span in payload (every span has a parent)")
        t0 = span_start_ns(root)

        spans = sorted((self._span(s, t0) for _, s in rows), key=lambda s: s.t_start)
        spans = _propagate_turn_ids(spans)
        return Trace(header=self.header(root, resource), spans=spans)

    def check_schema(self, resource: dict) -> None:
        """Override to reject a version this adapter predates. Never reject a version
        it merely does not recognise — that is how a consumer becomes single-producer."""

    def header(self, root: dict, resource: dict) -> CallHeader:
        end = span_end_ns(root)
        return CallHeader(
            call_id=str(root.get("traceId") or ""),
            source=resource.get("service.name", self.name),
            environment=resource.get("deployment.environment", "prod"),
            started_at=_dt(span_start_ns(root)),
            ended_at=_dt(end) if end is not None else None,
        )

    # --- per span ---------------------------------------------------------- #

    def _keep(self, key: str) -> bool:
        if key in _DROP or key.startswith(self.content_prefix):
            return False  # content is split out, not dropped — see _classify
        return self.keep_prefixes is None or key.startswith(self.keep_prefixes)

    def _classify(self, flat: dict[str, Any], stage: Stage) -> tuple[dict, dict]:
        """Split producer attributes into (canonical shape attrs, content by kind)."""
        n = len(self.content_prefix)
        rename = self.content_keys.get(stage, {})
        attrs, content = {}, {}
        for k, v in flat.items():
            if k.startswith(self.content_prefix):
                suffix = k[n:]
                content[rename.get(suffix, suffix)] = v
            elif k in self.content_attrs:
                content[self.content_attrs[k]] = v
            elif self._keep(k):
                attrs[self.attr_aliases.get(k, k)] = v
        return self.derive(attrs, stage), content

    def derive(self, attrs: dict, stage: Stage) -> dict:
        """Override for attributes that need more than a rename (one value fanning out
        into several flags, say). Returns the attrs to store."""
        return attrs

    def _span(self, s: dict, t0: int) -> Span:
        stage = self.stages.get(s["name"], Stage.UNKNOWN)
        raw = attrs_to_dict(s.get("attributes"))
        attrs, content = self._classify(raw, stage)
        end = span_end_ns(s)
        events = span_events(s)
        return Span(
            span_id=s["spanId"],
            parent_span_id=s.get("parentSpanId") or None,
            name=s["name"],
            stage=stage,
            t_start=round((span_start_ns(s) - t0) / 1e9, 6),
            t_end=round((end - t0) / 1e9, 6) if end is not None else None,
            turn_id=attrs.get("turn.id"),
            error=_span_errored(s, raw, events),
            attrs=attrs,
            content=content,
            events=[self._event(e, t0) for e in events],
        )

    def _event(self, ev: tuple[str, int, dict], t0: int) -> SpanEvent:
        name, ts, flat = ev
        attrs, content = self._classify(flat, Stage.UNKNOWN)
        return SpanEvent(
            name=name, t=round((ts - t0) / 1e9, 6), attrs=attrs, content=content
        )
