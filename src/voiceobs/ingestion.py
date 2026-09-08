"""Shared ingest logic, split across the two services:

- PRODUCE side (ingest service): `shard` an OTLP payload per call and `produce` each call's raw span
  slice to Kafka, keyed by call_id/trace_id. DB-free (no assembly here).
- CONSUME side (analysis service): `assemble_record` decompresses a record, resolves the call within
  the org schema (`identify`), and runs the write-path (`upsert_call` + `store_fragment`) — Postgres
  `RawFragment` stays the per-call assembly buffer, so `process()`/`assemble()` are unchanged.

The value on the wire is byte-identical to what `store_fragment` archives; a future Go ingest speaks
the same contract (see voiceobs/bus)."""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from typing import NamedTuple
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.bus import Producer, Record
from voiceobs.db.models import AgentScript, Call, RawFragment, Tombstone
from voiceobs.frameworks.otlp import attrs_to_dict

_CALL_ID_HINTS = ("voice.call_id",)


def _now() -> datetime:
    return datetime.now(UTC)


class Batch(NamedTuple):
    """One call's spans out of one OTLP request, with its identity resolved."""
    call_id: str | None
    trace_id: str
    root: dict | None
    resource: dict
    attrs: dict
    spans: list[dict]
    agent_id: str | None = None


# ── shared span helpers ──────────────────────────────────────────────────────────
def _root(spans: list[dict]) -> dict | None:
    return next((s for s in spans if not s.get("parentSpanId")), None)


def _attr(span: dict, keys: tuple[str, ...]) -> str | None:
    flat = attrs_to_dict(span.get("attributes"))
    return next((str(flat[k]) for k in keys if flat.get(k)), None)


def _hint(attrs: dict, spans: list[dict], keys: tuple[str, ...]) -> str | None:
    on_resource = next((str(attrs[k]) for k in keys if attrs.get(k)), None)
    return on_resource or next(filter(None, (_attr(s, keys) for s in spans)), None)


def shard(payload: dict) -> dict[str, tuple[dict, list[dict]]]:
    """Group spans into calls: producer call id if present, else traceId. The key is the Kafka
    partition key, so all of a call's batches co-partition."""
    out: dict[str, tuple[dict, list[dict]]] = {}
    for rs in payload.get("resourceSpans", []):
        resource = rs.get("resource", {})
        for scope in rs.get("scopeSpans", []):
            for span in scope.get("spans", []):
                key = _attr(span, _CALL_ID_HINTS) or span.get("traceId") or ""
                out.setdefault(key, (resource, []))[1].append(span)
    return out


def _slice_bytes(resource: dict, spans: list[dict]) -> bytes:
    slice_ = {"resourceSpans": [{"resource": resource, "scopeSpans": [{"spans": spans}]}]}
    return gzip.compress(json.dumps(slice_).encode())


# ── PRODUCE (ingest) ─────────────────────────────────────────────────────────────
def produce(producer: Producer, topic: str, payload: dict, *, org: str, agent_id: str | None) -> int:
    """Shard an OTLP payload and produce each call's gzipped slice to `topic`, keyed by
    call_id/trace_id. Returns the number of records produced. No DB access."""
    batch_id = uuid4().hex
    n = 0
    for seq, (key, (resource, spans)) in enumerate(shard(payload).items()):
        if not spans:
            continue
        trace_id = next((s["traceId"] for s in spans if s.get("traceId")), "")
        headers = {
            "org": org, "agent_id": agent_id or "", "shard_key": key,
            "trace_id": trace_id, "batch_id": batch_id, "seq": str(seq),
            "received_at": _now().isoformat(),
        }
        producer.send(topic, key or trace_id or batch_id, _slice_bytes(resource, spans), headers)
        n += 1
    producer.flush()
    return n


# ── CONSUME (analysis) ───────────────────────────────────────────────────────────
def identify(db: Session, resource: dict, spans: list[dict], agent_id: str | None) -> Batch:
    """Resolve this batch's call id within the already-pinned org schema."""
    attrs = attrs_to_dict(resource.get("attributes"))
    trace_id = next((s["traceId"] for s in spans if s.get("traceId")), "")
    root = _root(spans)
    call_id = _hint(attrs, [root, *spans] if root else spans, _CALL_ID_HINTS)
    if call_id is None and trace_id:
        call_id = db.scalar(select(Call.external_call_id).where(Call.trace_id == trace_id))
    return Batch(call_id=call_id or trace_id or None, trace_id=trace_id, root=root,
                 resource=resource, attrs=attrs, spans=spans, agent_id=agent_id)


def decode_record(record: Record) -> tuple[dict, list[dict]]:
    """A raw-spans record's gzipped slice → (resource, spans)."""
    slice_ = json.loads(gzip.decompress(record.value))
    rs = slice_["resourceSpans"][0]
    spans = [s for scope in rs.get("scopeSpans", []) for s in scope.get("spans", [])]
    return rs.get("resource", {}), spans


def tombstoned(db: Session, call_id: str | None) -> bool:
    return call_id is not None and db.get(Tombstone, call_id) is not None


def upsert_call(db: Session, b: Batch) -> None:
    call = db.scalar(select(Call).where(Call.external_call_id == b.call_id))
    if call is None and b.trace_id:
        call = _promote(db, b)
    if call is None:
        call = Call(
            external_call_id=b.call_id, trace_id=b.trace_id or None,
            source=b.attrs.get("service.name", "unknown"),
            environment=b.attrs.get("deployment.environment", "prod"),
            schema_version=b.attrs.get("voice.schema_version"),
            agent_id=b.agent_id, status="awaiting_media",
        )
        db.add(call)
    if call.trace_id is None and b.trace_id:
        call.trace_id = b.trace_id
    if call.agent_id is None and b.agent_id:
        call.agent_id = b.agent_id
    if call.prompt_id is None and call.agent_id:
        call.prompt_id = _active_script_prompt(db, call.agent_id)
    if b.root is not None:
        call.spans_complete = True
    call.last_activity_at = _now()


def _active_script_prompt(db: Session, agent_id: str) -> str | None:
    return db.scalar(select(AgentScript.prompt_id).where(
        AgentScript.agent_id == agent_id, AgentScript.active.is_(True)))


def _promote(db: Session, b: Batch) -> Call | None:
    call = db.scalar(select(Call).where(Call.trace_id == b.trace_id))
    if call is None:
        return None
    call.external_call_id = b.call_id
    return call


def store_fragment(db: Session, b: Batch, batch_id: str, seq: int) -> None:
    """Append the raw slice to the call's assembly buffer, idempotently (at-least-once safe: a
    redelivered (call_id, batch_id, seq) is a no-op via the unique constraint pre-check)."""
    call_pk = _call_pk(db, b.call_id)
    if call_pk is not None and db.scalar(select(RawFragment.id).where(
            RawFragment.call_id == call_pk, RawFragment.batch_id == batch_id,
            RawFragment.seq == seq)):
        return
    slice_ = {"resourceSpans": [{"resource": b.resource, "scopeSpans": [{"spans": b.spans}]}]}
    db.add(RawFragment(call_id=call_pk, batch_id=batch_id, seq=seq, received_at=_now(),
                       payload_gz=gzip.compress(json.dumps(slice_).encode())))


def _call_pk(db: Session, call_id: str | None) -> str | None:
    if call_id is None:
        return None
    call = db.scalar(select(Call).where(Call.external_call_id == call_id))
    return call.id if call else None
