"""The claim loop. Postgres is the queue — no broker, no Redis."""

from __future__ import annotations

import logging
import signal
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.config import get_config
from voiceobs.core.config import METRIC_VERSION
from voiceobs.db.models import Call
from voiceobs.db.session import get_session, org_schema_keys, use_org_schema
from voiceobs.frameworks import UnsupportedSchema
from voiceobs.judge import judge_call
from voiceobs.worker.process import process

log = logging.getLogger(__name__)

session_scope = contextmanager(get_session)

_s = get_config()
POLL_S = _s.worker_poll_s
BATCH = _s.worker_batch
# How long a call must be quiet before we analyse it without audio. Pipe 2 may never
# arrive for a given producer, and a call nobody can see is worse than one missing its
# waveform.
GRACE_S = _s.worker_grace_s


def claim(db: Session, *, batch: int = BATCH, grace_s: float = GRACE_S) -> list[Call]:
    """Calls ready to analyse, locked to this worker.

    SKIP LOCKED is what lets you scale by starting another container: two workers
    never see the same row. On SQLite it degrades to a plain select — fine, because
    nothing runs two workers against SQLite."""
    cutoff = datetime.now(UTC) - timedelta(seconds=grace_s)
    stmt = (
        select(Call)
        .where(
            Call.spans_complete.is_(True),
            Call.status != "unsupported",
            (Call.media_ready.is_(True)) | (Call.last_activity_at < cutoff),
            (Call.metric_version.is_(None)) | (Call.metric_version != METRIC_VERSION),
        )
        .order_by(Call.last_activity_at)
        .limit(batch)
    )
    if db.bind and db.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    return list(db.scalars(stmt))


def _maybe_judge(db: Session, call: Call) -> None:
    """Judge every call: judge_call self-gates on whether the post-call-analysis role is
    configured (resolve_llm) and never raises — a model failure is recorded, not propagated."""
    judge_call(db, call)


def tick(db: Session, **kw) -> int:
    """One pass. Returns how many calls were analysed."""
    calls = claim(db, **kw)
    for call in calls:
        try:
            status = process(db, call)
            log.info("analysed %s (%s)", call.external_call_id, status)
            _maybe_judge(db, call)
        except UnsupportedSchema as e:
            # Permanent: no amount of retrying makes this payload parseable.
            log.warning("unsupported %s: %s", call.external_call_id, e)
            call.status = "unsupported"
        except Exception:
            # Transient (a dropped connection, a bug). Leave the row untouched so the
            # next tick retries it; re-raise so the session rolls back cleanly.
            log.exception("failed %s", call.external_call_id)
            raise
    return len(calls)


def main() -> None:
    logging.basicConfig(level=get_config().log_level)
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    log.info("worker up (poll=%ss batch=%s grace=%ss)", POLL_S, BATCH, GRACE_S)
    while not stopping:
        done = 0
        try:
            with session_scope() as db:
                # sweep every org schema each cycle (one flat schema on SQLite)
                for org in org_schema_keys(db):
                    use_org_schema(db, org)
                    done += tick(db)
        except Exception:
            log.exception("tick failed")
            done = 0
        if not done:
            time.sleep(POLL_S)
    log.info("worker down")


if __name__ == "__main__":
    main()
