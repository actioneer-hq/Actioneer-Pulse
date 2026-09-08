"""Backfill worker: discover calls in an agent's blob store and analyse them audio-only.

A user triggers a `BackfillJob` (via the API); this sidecar claims `queued` jobs and drives each to
`done`, updating progress on the row as it goes (the SSE endpoint polls it). Discovery reuses the same
`driver.list` + `key_regex` + `file_map` shape as `worker/reconcile.py`, but where reconcile only
*attaches* audio to a pre-existing call, backfill *creates* the call (`ensure_audio_call`) and analyses
it (`process_audio_only`). Per-call failures are recorded on the Call (status='failed' +
analysis_error) and counted; they never abort the job.
"""

from __future__ import annotations

import logging
import re
import time
from contextlib import contextmanager

from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.config import get_config
from voiceobs.db.models import BackfillJob, Call, Media
from voiceobs.db.session import get_session, org_schema_keys, use_org_schema
from voiceobs.storage import ResolvedStorage, resolve_storage
from voiceobs.worker.process import ensure_audio_call, process_audio_only

log = logging.getLogger(__name__)
session_scope = contextmanager(get_session)


def _now():
    from datetime import UTC, datetime

    return datetime.now(UTC)


def discover(st: ResolvedStorage) -> dict[str, dict[str, str]]:
    """List the store and group objects by call_id → {media_kind: uri}, via the descriptor's
    key_regex + file_map (same convention as reconcile)."""
    objects = st.driver.list(st.descriptor, st.creds)
    key_re = re.compile(st.descriptor["key_regex"])
    id_group = st.descriptor.get("id_group", "call_id")
    file_map: dict = st.descriptor.get("file_map", {})
    base = f"{st.driver.scheme}://{st.descriptor['bucket']}/"
    out: dict[str, dict[str, str]] = {}
    for uri, _modified in objects:
        kind = file_map.get(uri.rsplit("/", 1)[-1])
        if kind is None:
            continue
        m = key_re.search(uri.removeprefix(base))
        if not m:
            continue
        call_id = m.groupdict().get(id_group)
        if call_id:
            out.setdefault(call_id, {})[kind] = uri
    return out


def run_job(db: Session, job: BackfillJob) -> None:
    """Execute one backfill job end-to-end within the already-pinned org schema. Commits per call so
    the SSE endpoint sees progress and analysed calls stream into the UI."""
    st = resolve_storage(db, job.agent_id)
    if st is None:
        _finish(db, job, status="failed", error="storage not configured for agent")
        return

    job.status = "scanning"
    job.updated_at = _now()
    db.commit()

    try:
        found = discover(st)
    except Exception as e:
        log.exception("backfill discover failed for job %s", job.id)
        _finish(db, job, status="failed", error=f"discover failed: {e}")
        return

    opts = job.options or {}
    use_stt = bool(opts.get("stt"))
    call_ids = sorted(found)
    limit = opts.get("limit")
    if limit:
        call_ids = call_ids[: int(limit)]
    job.total = len(call_ids)
    job.status = "running"
    job.phase = "analyzing"
    job.updated_at = _now()
    db.commit()

    for call_id in call_ids:
        if _is_cancelled(db, job.id):
            _finish(db, job, status="cancelled")
            return
        try:
            call = ensure_audio_call(db, job.agent_id, call_id)
            _register_media(db, call, found[call_id])
            status = process_audio_only(db, call, use_stt=use_stt)
            if status == "ok":
                job.completed += 1
            else:
                job.failed += 1
        except Exception as e:
            log.exception("backfill call %s failed", call_id)
            job.failed += 1
            job.error = job.error or f"{call_id}: {e}"
        job.updated_at = _now()
        db.commit()

    # Clusters once at the end (meaningful only when there is judgment prose — audio+STT / OTLP).
    job.status = "clustering"
    job.phase = "clustering"
    job.updated_at = _now()
    db.commit()
    try:
        from voiceobs.clustering.service import recluster

        recluster(db)
    except Exception:
        log.exception("backfill clustering failed for job %s", job.id)

    _finish(db, job, status="done")


def _register_media(db: Session, call: Call, kinds: dict[str, str]) -> None:
    """Register discovered audio objects as Media on the call (idempotent per kind)."""
    have = {m.kind for m in db.scalars(select(Media).where(Media.call_id == call.id))}
    for kind, uri in kinds.items():
        if kind not in have:
            db.add(Media(call_id=call.id, kind=kind, uri=uri))
    if kinds:
        call.media_ready = True
    db.flush()


def _is_cancelled(db: Session, job_id: str) -> bool:
    db.expire_all()
    return db.scalar(select(BackfillJob.status).where(BackfillJob.id == job_id)) == "cancelled"


def _finish(db: Session, job: BackfillJob, *, status: str, error: str | None = None) -> None:
    job.status = status
    job.phase = None
    if error:
        job.error = error
    job.finished_at = _now()
    job.updated_at = _now()
    db.commit()


def claim_next(db: Session) -> BackfillJob | None:
    """Claim the oldest queued job in the current schema (single-worker; no SKIP LOCKED needed)."""
    job = db.scalar(
        select(BackfillJob).where(BackfillJob.status == "queued").order_by(BackfillJob.created_at)
    )
    if job is None:
        return None
    job.status = "scanning"
    job.updated_at = _now()
    db.commit()
    return job


def _run_once() -> None:  # pragma: no cover
    with session_scope() as db:
        for org in org_schema_keys(db):
            use_org_schema(db, org)
            while (job := claim_next(db)) is not None:
                log.info("backfill: running job %s (org=%s)", job.id, org)
                run_job(db, job)


def main() -> None:  # pragma: no cover — entrypoint (one-shot, or a loop with an interval)
    logging.basicConfig(level=get_config().log_level)
    interval = getattr(get_config(), "backfill_interval_s", 0) or 0
    if not interval:
        _run_once()
        return
    while True:
        _run_once()
        time.sleep(interval)


if __name__ == "__main__":  # pragma: no cover
    main()
