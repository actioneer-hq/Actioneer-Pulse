"""Ingest endpoints. The `/traces` receiver is a thin Kafka producer: shard the OTLP batch per call
and produce each call's raw span slice to the `raw-spans` topic — the analysis service consumes,
assembles, and analyses. The other producer endpoints (artifacts/transcript/prompt/erase) are direct
DB writes and stay synchronous."""

from __future__ import annotations

import gzip
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from voiceobs.api.deps import now, session_dep
from voiceobs.api.schemas import ArtifactIn, PromptIn, TranscriptIn
from voiceobs.auth import resolve_ingest_token
from voiceobs.auth.env import dev_open
from voiceobs.bus import get_producer
from voiceobs.config import get_config
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
from voiceobs.db.session import use_org_schema
from voiceobs.frameworks.otlp import decode_protobuf
from voiceobs.ingestion import produce

router = APIRouter(prefix="/v1")

# Schema-per-tenant: the org (schema) is chosen from this header. Under dev-open / single-tenant
# SQLite it defaults to "default". In multi-org Postgres a producer sends its org slug here; the
# ingest token is validated within that schema, and the slug rides the Kafka header so the consumer
# pins the same schema.
_ORG_HEADER = "X-Voiceobs-Org"


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


def ingest_identity(
    db: Session = Depends(session_dep),
    authorization: str | None = Header(None),
    x_token: str | None = Header(None, alias="X-Voiceobs-Token"),
    x_org: str = Header("default", alias=_ORG_HEADER),
) -> tuple[str | None, str | None]:
    """(org_id, agent_id) a producer authenticated as, or (None, None) under dev-open.

    Routes to the org's schema first (from the X-Voiceobs-Org header), then validates the
    per-agent ingest token *within* that schema — the token names the agent. Without a token,
    ingest is refused UNLESS dev-open (local/tests)."""
    use_org_schema(db, x_org)  # pick the schema before any DB lookup (incl. the token)
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    token = token or x_token
    if token:
        resolved = resolve_ingest_token(db, token)
        if resolved is None:
            raise HTTPException(401, "invalid ingest token")
        return resolved
    if dev_open():
        return (None, None)
    raise HTTPException(401, "ingest token required")


@router.post("/traces")
def ingest_traces(
    payload: dict = Depends(otlp_payload),
    identity: tuple[str | None, str | None] = Depends(ingest_identity),
    x_org: str = Header("default", alias=_ORG_HEADER),
) -> dict:
    """OTLP receiver — a thin producer. Always 200. Auth (ingest_identity) already validated the
    token in the org's schema; here we shard the batch and produce each call's raw slice to Kafka
    keyed by call_id/trace_id (org slug rides the header). No DB writes — the analysis consumer
    assembles + analyses."""
    _token_org, token_agent = identity
    produce(get_producer(), get_config().kafka_topic_raw, payload, org=x_org, agent_id=token_agent)
    return {"partialSuccess": {}}


@router.post("/calls/{call_id}/artifacts")
def register_artifact(
    call_id: str, body: ArtifactIn, db: Session = Depends(session_dep),
    x_org: str = Header("default", alias=_ORG_HEADER),
) -> dict:
    use_org_schema(db, x_org)
    call = _get_call(db, call_id)
    if db.scalar(
        select(Media).where(
            Media.call_id == call.id, Media.kind == body.kind, Media.sha256 == body.sha256
        )
    ):
        return {"status": "exists"}
    db.add(Media(
        call_id=call.id, kind=body.kind, uri=body.uri,
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
    x_org: str = Header("default", alias=_ORG_HEADER),
) -> dict:
    use_org_schema(db, x_org)
    existing = db.scalar(
        select(Prompt).where(Prompt.template_sha256 == body.template_sha256)
    )
    if existing:
        response.status_code = 200
        return {"status": "exists"}
    db.add(Prompt(template_sha256=body.template_sha256, text=body.text))
    return {"status": "created"}


@router.post("/calls/{call_id}/transcript")
def upload_transcript(
    call_id: str, body: TranscriptIn, db: Session = Depends(session_dep),
    x_org: str = Header("default", alias=_ORG_HEADER),
) -> dict:
    """BYO transcript — one per call, re-upload replaces. Overrides the derived one."""
    use_org_schema(db, x_org)
    call = _get_call(db, call_id)
    row = db.scalar(select(Transcript).where(Transcript.call_id == call.id))
    if row is None:
        row = Transcript(call_id=call.id)
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
    x_org: str = Header("default", alias=_ORG_HEADER),
) -> dict:
    if not get_config().allow_delete or confirm != call_id:
        raise HTTPException(403, "erasure requires X-Voiceobs-Confirm and VOICEOBS_ALLOW_DELETE=1")
    use_org_schema(db, x_org)
    call = _get_call(db, call_id)
    db.add(Tombstone(call_id=call_id, deleted_by="api"))
    for model in (Turn, Event, Metric, Utterance, Media, RawFragment, IngestRun,
                  Annotation, Label, Transcript, Judgment):
        db.execute(delete(model).where(model.call_id == call.id))
    db.delete(call)
    return {"status": "erased"}


def _get_call(db: Session, call_id: str) -> Call:
    call = db.scalar(select(Call).where(Call.external_call_id == call_id))
    if call is None:
        raise HTTPException(404, "call not found")
    return call
