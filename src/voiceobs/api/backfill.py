"""Backfill API: trigger a blob-storage backfill, watch its progress (SSE), and cancel it.

The worker (`voiceobs.worker.backfill`) does the actual analysis; this router only enqueues a
`BackfillJob` and streams progress + newly-analysed calls to the UI. Owner/admin only.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.api.deps import now, session_dep
from voiceobs.api.read import _list_item
from voiceobs.auth import current_membership, require_role
from voiceobs.db.models import BackfillJob, Call, Membership, Organization
from voiceobs.db.session import get_session, use_org_schema
from voiceobs.storage import resolve_storage
from voiceobs.worker.backfill import discover, discover_otlp

router = APIRouter(prefix="/v1/backfill")

_POLL_S = 1.0
_HEARTBEAT_EVERY = 15
_BOARDS_EVERY = 200  # emit a boards-refresh signal every N analysed calls (debounced board refresh)


class BackfillIn(BaseModel):
    agent_id: str | None = None
    source: str = "audio"
    options: dict = {}


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


def _job_dict(j: BackfillJob) -> dict:
    return {
        "id": j.id, "agent_id": j.agent_id, "source": j.source, "status": j.status,
        "phase": j.phase, "total": j.total, "completed": j.completed, "failed": j.failed,
        "error": j.error, "created_at": j.created_at, "finished_at": j.finished_at,
    }


@router.get("/preview")
def preview(
    agent_id: str,
    source: str = "audio",
    db: Session = Depends(session_dep),
    mem: Membership = Depends(require_role("owner", "admin")),
) -> dict:
    """Discover how many calls sit in the agent's store, so the UI can say 'you have N calls…'.
    Lightweight: lists + groups by call id, does not fetch bytes. `source` selects audio vs OTLP."""
    st = resolve_storage(db, agent_id)
    if st is None:
        raise HTTPException(400, "storage not configured/enabled for this agent")
    try:
        if source == "otlp":
            found_otlp = discover_otlp(st)
            return {"agent_id": agent_id, "source": "otlp", "audio_calls": len(found_otlp),
                    "files": len(found_otlp), "sample_call_ids": sorted(found_otlp)[:5]}
        if source == "manifest":
            from voiceobs.integration import discover_manifest, resolve_manifest

            resolved_mf = resolve_manifest(db, agent_id)
            if resolved_mf is None:
                raise HTTPException(400, "no integration manifest registered for this agent")
            found_mf = discover_manifest(st, resolved_mf[0])
            return {"agent_id": agent_id, "source": "manifest", "audio_calls": len(found_mf),
                    "files": sum(len(v) for v in found_mf.values()),
                    "sample_call_ids": sorted(found_mf)[:5]}
        found = discover(st)
    except Exception as e:
        raise HTTPException(400, f"could not list storage: {e}") from e
    return {
        "agent_id": agent_id,
        "source": "audio",
        "audio_calls": len(found),
        "files": sum(len(v) for v in found.values()),
        "sample_call_ids": sorted(found)[:5],
    }


@router.post("", status_code=201)
def create(
    body: BackfillIn,
    db: Session = Depends(session_dep),
    mem: Membership = Depends(require_role("owner", "admin")),
) -> dict:
    """Enqueue a backfill job. The backfill worker (a sidecar) claims and runs it."""
    if body.source not in ("audio", "otlp", "manifest"):
        raise HTTPException(400, "source must be 'audio', 'otlp' or 'manifest'")
    if resolve_storage(db, body.agent_id) is None:
        raise HTTPException(400, "storage not configured/enabled for this agent")
    job = BackfillJob(
        org_id=mem.org_id, agent_id=body.agent_id, source=body.source,
        options=body.options or {}, status="queued", created_at=now(),
    )
    db.add(job)
    db.flush()
    return {"id": job.id, "status": job.status}


@router.get("/{job_id}")
def get_job(
    job_id: str,
    db: Session = Depends(session_dep),
    mem: Membership = Depends(current_membership),
) -> dict:
    job = db.get(BackfillJob, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return _job_dict(job)


@router.post("/{job_id}/cancel")
def cancel(
    job_id: str,
    db: Session = Depends(session_dep),
    mem: Membership = Depends(require_role("owner", "admin")),
) -> dict:
    job = db.get(BackfillJob, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    if job.status not in ("done", "failed", "cancelled"):
        job.status = "cancelled"
        job.updated_at = now()
    return _job_dict(job)


@router.get("/{job_id}/events")
def events(
    job_id: str,
    db: Session = Depends(session_dep),
    mem: Membership = Depends(current_membership),
) -> StreamingResponse:
    """SSE: progress ticks, each newly-analysed call, a boards-refresh signal every N calls, and a
    final done summary. Mirrors boards.py's poll-cursor-diff-push shape."""
    org_slug = db.scalar(select(Organization.slug))  # one org per schema
    return StreamingResponse(
        _stream(job_id, org_slug), media_type="text/event-stream"
    )


def _stream(job_id: str, org_slug: str) -> Iterator[str]:
    db = next(get_session())
    try:
        use_org_schema(db, org_slug)  # this session skipped request auth — pin the schema here
        job = db.get(BackfillJob, job_id)
        if job is None:
            yield _sse({"type": "error", "error": "job not found"})
            return
        seen: set[str] = set()
        last_boards = 0
        idle = 0
        while True:
            db.rollback()  # end the implicit txn so each read sees freshly committed rows
            job = db.get(BackfillJob, job_id)
            yield _sse({"type": "progress", "data": _job_dict(job)})

            for item in _new_calls(db, job, seen):
                yield _sse({"type": "call-analyzed", "data": item})
                idle = 0

            if job.completed - last_boards >= _BOARDS_EVERY:
                last_boards = job.completed
                yield _sse({"type": "boards-refresh"})

            if job.status in ("done", "failed", "cancelled"):
                yield _sse({"type": "done", "data": _job_dict(job)})
                return

            idle += 1
            if idle % _HEARTBEAT_EVERY == 0:
                yield ": keep-alive\n\n"
            time.sleep(_POLL_S)
    except GeneratorExit:
        return
    finally:
        db.close()


def _new_calls(db: Session, job: BackfillJob, seen: set[str]) -> list[dict]:
    """Calls analysed by this job we haven't emitted yet — this agent's calls created at/after the
    job started, that have been analysed or failed."""
    stmt = select(Call).where(
        Call.created_at >= job.created_at,
        Call.status.in_(("ingested", "failed")),
    ).order_by(Call.created_at)
    if job.agent_id:
        stmt = stmt.where(Call.agent_id == job.agent_id)
    out = []
    for c in db.scalars(stmt):
        if c.id not in seen:
            seen.add(c.id)
            out.append(_list_item(c, None))
    return out
