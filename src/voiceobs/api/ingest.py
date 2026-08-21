"""Ingest endpoints. Validate → store → return fast; no adapter/metrics work here
(that runs in the worker). OTLP batches are sharded per call into RawFragment."""

from __future__ import annotations

import gzip
import json
import os
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from voiceobs.adapters.otlp import attrs_to_dict, iter_spans
from voiceobs.api.deps import now, session_dep
from voiceobs.api.schemas import ArtifactIn, PromptIn
from voiceobs.db.models import (
    Annotation,
    Call,
    Event,
    IngestRun,
    Label,
    Media,
    Metric,
    Prompt,
    RawFragment,
    Tombstone,
    Turn,
    Utterance,
)

router = APIRouter(prefix="/v1")

_ROOT_SPAN = "voice.call"


@router.post("/traces")
def ingest_traces(payload: dict, db: Session = Depends(session_dep)) -> dict:
    """OTLP receiver. Always 200 — never 4xx a partial batch."""
    batch_id = uuid4().hex
    rejected = 0
    for seq, (call_id, rows) in enumerate(_shard(payload).items()):
        resource, spans = rows[0][0], [s for _, s in rows]
        tenant = _tenant(resource, spans)
        if _tombstoned(db, tenant, call_id):
            rejected += len(spans)
            continue
        if call_id is not None:
            _upsert_call(db, tenant, call_id, resource, spans)
        _store_fragment(db, tenant, call_id, batch_id, seq, resource, spans)
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
    if body.kind == "audio":
        call.media_ready = True
        call.channel_map = body.channel_map
        call.sample_rate = body.sample_rate
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
                  Annotation, Label):
        db.execute(delete(model).where(model.call_id == call.id))
    db.delete(call)
    return {"status": "erased"}


# --- helpers ---------------------------------------------------------------- #


def _shard(payload: dict) -> dict[str | None, list[tuple[dict, dict]]]:
    """Group (resource, span) rows by voice.call_id (None = unattributed)."""
    out: dict[str | None, list[tuple[dict, dict]]] = {}
    for resource, span in iter_spans(payload):
        call_id = attrs_to_dict(span.get("attributes")).get("voice.call_id")
        out.setdefault(call_id, []).append((resource, span))
    return out


def _tenant(resource: dict, spans: list[dict]) -> str:
    for s in spans:
        t = attrs_to_dict(s.get("attributes")).get("voice.tenant_id")
        if t:
            return str(t)
    return "default"


def _root(spans: list[dict]) -> dict | None:
    return next((s for s in spans if s.get("name") == _ROOT_SPAN), None)


def _upsert_call(
    db: Session, tenant: str, call_id: str, resource: dict, spans: list[dict]
) -> None:
    root = _root(spans)
    call = db.scalar(
        select(Call).where(Call.tenant_id == tenant, Call.external_call_id == call_id)
    )
    if call is None:
        call = Call(
            tenant_id=tenant, external_call_id=call_id,
            source=resource.get("service.name", "unknown"),
            environment=resource.get("deployment.environment", "prod"),
            schema_version=resource.get("voice.schema_version"),
            status="awaiting_media",
        )
        db.add(call)
    if root is not None:
        call.spans_complete = True
    call.last_activity_at = now()


def _store_fragment(
    db: Session, tenant: str, call_id: str | None, batch_id: str, seq: int,
    resource: dict, spans: list[dict],
) -> None:
    slice_ = {"resourceSpans": [{"resource": {}, "scopeSpans": [{"spans": spans}]}]}
    db.add(RawFragment(
        tenant_id=tenant, call_id=_call_pk(db, tenant, call_id),
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
