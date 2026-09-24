"""Pull-path ingest sidecar for file-based producers with no OTLP exporter.

For each agent whose integration manifest declares `ingest_method="storage_polling"`, periodically
sweep its store, discover settled artifacts via the manifest's path selectors, and run each new call
through the manifest runtime (`process_manifest_call`) — the same fetch→decode→map→assemble→analyse
tail the one-shot `source=manifest` backfill uses. This is the continuous counterpart of that
backfill and the audio-only `reconcile` loop.

Two gates keep it honest, mirroring reconcile: a **settle grace** (`poller_grace_s`) so a call whose
artifacts are still being written isn't ingested half-complete, and a per-agent **watermark**
(`last_polled_modified`) so a sweep re-lists cheaply but only reprocesses calls whose newest object
advanced past it. Reprocessing is always safe — `process_trace` delete-then-inserts — so the
watermark is a cost optimisation, not a correctness dependency; a late-arriving artifact advances the
call's max mtime and re-triggers ingest on the next sweep.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.bus import get_producer
from voiceobs.config import get_config
from voiceobs.db.models import AgentIntegrationManifest
from voiceobs.db.session import get_session, org_schema_keys, use_org_schema
from voiceobs.integration import discover_manifest_windowed, process_manifest_call
from voiceobs.judge.queue import enqueue_judge
from voiceobs.storage import resolve_storage

log = logging.getLogger(__name__)
session_scope = contextmanager(get_session)


def poll(db: Session, org: str = "default") -> int:
    """Sweep every storage_polling agent in the current schema. Returns calls ingested."""
    cutoff = datetime.now(UTC) - timedelta(seconds=get_config().poller_grace_s)
    total = 0
    rows = db.scalars(
        select(AgentIntegrationManifest).where(
            AgentIntegrationManifest.ingest_method == "storage_polling"
        )
    ).all()
    for row in rows:
        st = resolve_storage(db, row.agent_id)
        if st is None:
            continue  # storage not configured yet — nothing to poll
        try:
            total += _poll_agent(db, org, row, st, cutoff)
        except Exception:
            log.exception("poller: sweep failed for agent %s", row.agent_id)
    return total


def _poll_agent(db: Session, org: str, row: AgentIntegrationManifest, st, cutoff: datetime) -> int:
    """List + window one agent's store, ingest each new settled call, advance the watermark."""
    found = discover_manifest_windowed(st, row.manifest, row.last_polled_modified, cutoff)
    if not found:
        return 0
    n = 0
    high = row.last_polled_modified
    if high is not None and high.tzinfo is None:
        high = high.replace(tzinfo=UTC)  # DB round-trips can drop tzinfo
    for call_id, (items, max_mtime) in sorted(found.items(), key=lambda kv: kv[1][1]):
        judge_cid = None
        try:
            status = process_manifest_call(
                db, row.agent_id, call_id, items, st.creds, row.manifest, row.version
            )
            if status in ("ok", "partial"):
                judge_cid = call_id  # transcript-bearing manifest calls are judgeable
                n += 1
        except Exception:
            log.exception("poller: call %s failed for agent %s", call_id, row.agent_id)
            db.rollback()
            continue
        high = max_mtime if high is None else max(high, max_mtime)
        row.last_polled_modified = high  # advance so the next sweep skips settled calls
        db.commit()
        if judge_cid:  # enqueue after the commit → backfill-priority judge queue
            enqueue_judge(get_producer(), org, judge_cid, backfill=True)
    return n


def _run_once() -> None:  # pragma: no cover
    with session_scope() as db:
        for org in org_schema_keys(db):  # sweep each org's schema (one flat schema on SQLite)
            use_org_schema(db, org)
            log.info("polled %s: %d call(s)", org, poll(db, org))


def main() -> None:  # pragma: no cover — entrypoint
    """One-shot, or a sidecar loop when VOICEOBS_POLLER_INTERVAL_S is set."""
    logging.basicConfig(level=get_config().log_level)
    interval = get_config().poller_interval_s
    if not interval:
        _run_once()
        return
    while True:
        _run_once()
        time.sleep(interval)


if __name__ == "__main__":  # pragma: no cover
    main()
