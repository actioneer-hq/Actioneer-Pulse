"""Ingest endpoints. Validate → store → return fast; no adapter/metrics work here
(that runs in the worker). OTLP batches are sharded per call into RawFragment."""

from __future__ import annotations

import gzip
import json
import os
from typing import NamedTuple
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from voiceobs.adapters.otlp import attrs_to_dict, decode_protobuf
from voiceobs.api.deps import now, session_dep
from voiceobs.api.schemas import ArtifactIn, PromptIn, TranscriptIn
from voiceobs.db.models import (
    Annotation,
    Call,
    Event,
    IngestRun,
    Judgment,
    Label,
    Media,
    Metric,
    Prompt,
    RawFragment,
    Tombstone,
    Transcript,
    Turn,
    Utterance,
)

router = APIRouter(prefix="/v1")

# Producer-specific attribute names. Ingest runs before any adapter, so it can only
# look for names it already knows; each is optional and falls back to something OTLP
# itself guarantees. A new producer adds its name here, not new logic.
_CALL_ID_HINTS = ("voice.call_id",)
_TENANT_HINTS = ("voice.tenant_id",)


async def otlp_payload(request: Request) -> dict:
    """OTLP/HTTP body -> dict, whichever wire format arrived.

    An async dependency rather than the endpoint itself: the endpoint stays sync so its
    blocking DB work keeps running in the threadpool."""
    raw = await request.body()
    if "gzip" in request.headers.get("content-encoding", "").lower():
        raw = gzip.decompress(raw)
    if "protobuf" in request.headers.get("content-type", ""):
        return decode_protobuf(raw)
    try:
        return json.loads(raw) if raw else {}
    except ValueError as e:
        raise HTTPException(400, f"unreadable OTLP body: {e}") from e


@router.post("/traces")
def ingest_traces(
    payload: dict = Depends(otlp_payload),
    db: Session = Depends(session_dep),
    header_tenant: str | None = Header(None, alias="X-Voiceobs-Tenant"),
) -> dict:
    """OTLP receiver. Always 200 — never 4xx a partial batch."""
    batch_id = uuid4().hex
    rejected = 0
    for seq, (resource, spans) in enumerate(_shard(payload).values()):
        batch = _identify(db, resource, spans, header_tenant)
        if _tombstoned(db, batch.tenant, batch.call_id):
            rejected += len(spans)
            continue
        if batch.call_id is not None:
            _upsert_call(db, batch)
        _store_fragment(db, batch, batch_id, seq)
    return {"partialSuccess": {"rejectedSpans": rejected} if rejected else {}}


@router.post("/calls/{call_id}/artifacts")
def register_artifact(
    call_id: str, body: ArtifactIn, db: Session = Depends(session_dep)
) -> dict:
    call = _get_call(db, call_id)
    if db.scalar(
        select(Media).where(
            Media.call_id == call.id, Media.kind == body.kind, Media.sha256 == body.sha256
        )
    ):
        return {"status": "exists"}
    db.add(Media(
        call_id=call.id, tenant_id=call.tenant_id, kind=body.kind, uri=body.uri,
        sha256=body.sha256, bytes=body.bytes, content_type=body.content_type,
        channels=body.channels, sample_rate=body.sample_rate,
    ))
    if body.kind.startswith("audio"):  # "audio" (stereo) or "audio_caller"/"audio_agent"
        call.media_ready = True
        call.channel_map = body.channel_map or call.channel_map
        call.sample_rate = body.sample_rate or call.sample_rate
        if body.t0_offset_s is not None:
            call.audio_t0_offset_s = body.t0_offset_s
        if call.spans_complete:
            call.status = "ingested"
    call.last_activity_at = now()
    return {"status": "ok", "media_ready": call.media_ready}


@router.post("/prompts", status_code=201)
def register_prompt(
    body: PromptIn,
    response: Response,
    db: Session = Depends(session_dep),
    tenant: str = Header("default", alias="X-Voiceobs-Tenant"),
) -> dict:
    existing = db.scalar(
        select(Prompt).where(
            Prompt.tenant_id == tenant, Prompt.template_sha256 == body.template_sha256
        )
    )
    if existing:
        response.status_code = 200
        return {"status": "exists"}
    db.add(Prompt(tenant_id=tenant, template_sha256=body.template_sha256, text=body.text))
    return {"status": "created"}


@router.post("/calls/{call_id}/transcript")
def upload_transcript(
    call_id: str, body: TranscriptIn, db: Session = Depends(session_dep)
) -> dict:
    """BYO transcript — one per call, re-upload replaces. Overrides the derived one."""
    call = _get_call(db, call_id)
    row = db.scalar(select(Transcript).where(Transcript.call_id == call.id))
    if row is None:
        row = Transcript(call_id=call.id, tenant_id=call.tenant_id)
        db.add(row)
    row.source, row.format, row.content, row.uri = (
        body.source, body.format, body.text, body.uri
    )
    return {"status": "ok"}


@router.delete("/calls/{call_id}")
def erase_call(
    call_id: str,
    db: Session = Depends(session_dep),
    confirm: str = Header("", alias="X-Voiceobs-Confirm"),
) -> dict:
    if os.getenv("VOICEOBS_ALLOW_DELETE") != "1" or confirm != call_id:
        raise HTTPException(403, "erasure requires X-Voiceobs-Confirm and VOICEOBS_ALLOW_DELETE=1")
    call = _get_call(db, call_id)
    db.add(Tombstone(tenant_id=call.tenant_id, call_id=call_id, deleted_by="api"))
    for model in (Turn, Event, Metric, Utterance, Media, RawFragment, IngestRun,
                  Annotation, Label, Transcript, Judgment):
        db.execute(delete(model).where(model.call_id == call.id))
    db.delete(call)
    return {"status": "erased"}


# --- helpers ---------------------------------------------------------------- #


class _Batch(NamedTuple):
    """One call's spans out of one OTLP request, with its identity resolved."""

    tenant: str
    call_id: str | None
    trace_id: str
    root: dict | None  # the trace root, when this batch happened to carry it
    resource: dict  # raw OTLP resource — archived verbatim
    attrs: dict  # the same, flattened
    spans: list[dict]


def _shard(payload: dict) -> dict[str, tuple[dict, list[dict]]]:
    """Group spans into calls: producer call id if there is one, else traceId.

    call_id survives a reconnect splitting one call across two traces; traceId is all a
    producer that never heard of `voice.call_id` (Pipecat, LiveKit) has. Not `iter_spans`
    because the archive needs the resource unflattened."""
    out: dict[str, tuple[dict, list[dict]]] = {}
    for rs in payload.get("resourceSpans", []):
        resource = rs.get("resource", {})
        for scope in rs.get("scopeSpans", []):
            for span in scope.get("spans", []):
                key = _attr(span, _CALL_ID_HINTS) or span.get("traceId") or ""
                out.setdefault(key, (resource, []))[1].append(span)
    return out


def _identify(
    db: Session, resource: dict, spans: list[dict], header_tenant: str | None
) -> _Batch:
    """Who this batch belongs to. The root closes last, so its batch lands after its
    children and may carry no identity at all: fall back resource -> spans -> header ->
    what this trace already resolved to -> the trace id itself."""
    attrs = attrs_to_dict(resource.get("attributes"))
    trace_id = next((s["traceId"] for s in spans if s.get("traceId")), "")
    root = _root(spans)

    tenant = _hint(attrs, spans, _TENANT_HINTS) or header_tenant
    # root first — a producer that stamps the call id on the root alone is still found
    call_id = _hint(attrs, [root, *spans] if root else spans, _CALL_ID_HINTS)
    if (tenant is None or call_id is None) and trace_id:
        known = db.execute(
            select(Call.tenant_id, Call.external_call_id).where(Call.trace_id == trace_id)
        ).first()
        if known:
            tenant, call_id = tenant or known[0], call_id or known[1]

    return _Batch(
        tenant=str(tenant or "default"),
        call_id=call_id or trace_id or None,
        trace_id=trace_id, root=root, resource=resource, attrs=attrs, spans=spans,
    )


def _root(spans: list[dict]) -> dict | None:
    """Parentless span. OTLP's own definition of a root, so it holds for any producer —
    keying off the name `voice.call` would leave foreign calls forever incomplete."""
    return next((s for s in spans if not s.get("parentSpanId")), None)


def _attr(span: dict, keys: tuple[str, ...]) -> str | None:
    flat = attrs_to_dict(span.get("attributes"))
    return next((str(flat[k]) for k in keys if flat.get(k)), None)


def _hint(attrs: dict, spans: list[dict], keys: tuple[str, ...]) -> str | None:
    """Resource first — it rides every export; a root-span attribute arrives only in
    the last one."""
    on_resource = next((str(attrs[k]) for k in keys if attrs.get(k)), None)
    return on_resource or next(filter(None, (_attr(s, keys) for s in spans)), None)


def _upsert_call(db: Session, b: _Batch) -> None:
    call = db.scalar(
        select(Call).where(
            Call.tenant_id == b.tenant, Call.external_call_id == b.call_id
        )
    )
    if call is None and b.trace_id:
        call = _promote(db, b)
    if call is None:
        call = Call(
            tenant_id=b.tenant, external_call_id=b.call_id, trace_id=b.trace_id or None,
            source=b.attrs.get("service.name", "unknown"),
            environment=b.attrs.get("deployment.environment", "prod"),
            schema_version=b.attrs.get("voice.schema_version"),
            status="awaiting_media",
        )
        db.add(call)
    if call.trace_id is None and b.trace_id:
        call.trace_id = b.trace_id
    if b.root is not None:
        call.spans_complete = True
    call.last_activity_at = now()


def _promote(db: Session, b: _Batch) -> Call | None:
    """Rename the provisional call this trace opened under its trace id. Inserting
    instead would split one conversation across two rows."""
    call = db.scalar(select(Call).where(Call.trace_id == b.trace_id))
    if call is None:
        return None
    if call.tenant_id != b.tenant:
        db.execute(
            update(RawFragment)
            .where(RawFragment.call_id == call.id)
            .values(tenant_id=b.tenant)
        )
        call.tenant_id = b.tenant
    call.external_call_id = b.call_id
    return call


def _store_fragment(db: Session, b: _Batch, batch_id: str, seq: int) -> None:
    # Keep the resource verbatim — service.name routes the adapter on replay, so a
    # blank one makes the archive unreplayable.
    slice_ = {"resourceSpans": [{"resource": b.resource, "scopeSpans": [{"spans": b.spans}]}]}
    db.add(RawFragment(
        tenant_id=b.tenant, call_id=_call_pk(db, b.tenant, b.call_id),
        batch_id=batch_id, seq=seq, received_at=now(),
        payload_gz=gzip.compress(json.dumps(slice_).encode()),
    ))


def _call_pk(db: Session, tenant: str, call_id: str | None) -> str | None:
    if call_id is None:
        return None
    call = db.scalar(
        select(Call).where(Call.tenant_id == tenant, Call.external_call_id == call_id)
    )
    return call.id if call else None


def _tombstoned(db: Session, tenant: str, call_id: str | None) -> bool:
    if call_id is None:
        return False
    return db.get(Tombstone, {"tenant_id": tenant, "call_id": call_id}) is not None


def _get_call(db: Session, call_id: str) -> Call:
    call = db.scalar(select(Call).where(Call.external_call_id == call_id))
    if call is None:
        raise HTTPException(404, "call not found")
    return call
