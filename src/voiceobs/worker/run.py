"""The analysis consumer. Kafka is the queue: drain `raw-spans`, assemble each record into the
call's RawFragment buffer (Postgres remains the assembly authority), and analyse when ready.

Readiness has two paths, mirroring the old claim() predicate:
- fast path — a batch that leaves the call spans_complete + media_ready is analysed immediately;
- grace path — a spans_complete call with no audio is analysed after `worker_grace_s` of quiet, via
  a periodic timeout flush (a timeout, not a work queue — no SKIP LOCKED).

At-least-once: the offset is committed AFTER the DB commit; redelivery is safe because store_fragment
is idempotent and process() is delete-then-insert gated on metric_version. Poison records go to the
DLQ after bounded retries."""

from __future__ import annotations

import logging
import signal
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.bus import Record, get_consumer, get_producer
from voiceobs.config import get_config
from voiceobs.core.config import METRIC_VERSION
from voiceobs.db.models import Call
from voiceobs.db.session import get_session, org_schema_keys, use_org_schema
from voiceobs.frameworks import UnsupportedSchema
from voiceobs.ingestion import decode_record, identify, store_fragment, tombstoned, upsert_call
from voiceobs.judge import judge_call
from voiceobs.worker.process import process

log = logging.getLogger(__name__)

session_scope = contextmanager(get_session)


def _ready_now(call: Call) -> bool:
    """Fast path: audio is present and the call hasn't been analysed at the current metric version."""
    return bool(
        call.spans_complete and call.media_ready and call.status != "unsupported"
        and (call.metric_version is None or call.metric_version != METRIC_VERSION)
    )


def _analyse(db: Session, call: Call) -> None:
    try:
        status = process(db, call)
        log.info("analysed %s (%s)", call.external_call_id, status)
        judge_call(db, call)
    except UnsupportedSchema as e:  # permanent — no retry makes this payload parseable
        log.warning("unsupported %s: %s", call.external_call_id, e)
        call.status = "unsupported"


def handle_record(db: Session, record: Record) -> None:
    """Assemble one raw-spans record into its call and analyse if ready. Idempotent."""
    org = record.headers.get("org") or "default"
    agent_id = record.headers.get("agent_id") or None
    batch_id = record.headers["batch_id"]
    seq = int(record.headers["seq"])
    use_org_schema(db, org)
    resource, spans = decode_record(record)
    b = identify(db, resource, spans, agent_id)
    if tombstoned(db, b.call_id):
        return
    if b.call_id is not None:
        upsert_call(db, b)
    store_fragment(db, b, batch_id, seq)
    db.flush()
    if b.call_id is not None:
        call = db.scalar(select(Call).where(Call.external_call_id == b.call_id))
        if call is not None and _ready_now(call):
            _analyse(db, call)


def flush_due(db: Session) -> int:
    """Grace path: analyse spans-complete calls that have waited out the grace window (or have audio
    but weren't caught by the fast path). Swept across every org schema. Returns count analysed."""
    cutoff = datetime.now(UTC) - timedelta(seconds=get_config().worker_grace_s)
    batch = get_config().worker_batch
    total = 0
    for org in org_schema_keys(db):
        use_org_schema(db, org)
        stmt = (
            select(Call).where(
                Call.spans_complete.is_(True), Call.status != "unsupported",
                (Call.media_ready.is_(True)) | (Call.last_activity_at < cutoff),
                (Call.metric_version.is_(None)) | (Call.metric_version != METRIC_VERSION),
            ).order_by(Call.last_activity_at).limit(batch)
        )
        for call in db.scalars(stmt):
            _analyse(db, call)
            total += 1
        db.commit()
    return total


def main() -> None:  # pragma: no cover — the long-running consumer loop
    logging.basicConfig(level=get_config().log_level)
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    c = get_config()
    consumer = get_consumer(c.kafka_consumer_group, [c.kafka_topic_raw])
    log.info("analysis consumer up (topic=%s group=%s)", c.kafka_topic_raw, c.kafka_consumer_group)
    last_flush = time.monotonic()
    try:
        while not stopping:
            record = consumer.poll(1.0)
            if record is not None and _consume_one(consumer, record):
                consumer.commit(record)
            if time.monotonic() - last_flush >= c.worker_poll_s:
                try:
                    with session_scope() as db:
                        flush_due(db)
                except Exception:
                    log.exception("grace flush failed")
                last_flush = time.monotonic()
    finally:
        consumer.close()
    log.info("analysis consumer down")


def _consume_one(consumer, record: Record) -> bool:  # pragma: no cover
    """Process one record with bounded retries; poison records go to the DLQ. Returns True if the
    offset should be committed (success or DLQ'd)."""
    for attempt in range(get_config().kafka_max_retries):
        try:
            with session_scope() as db:
                handle_record(db, record)
            return True
        except Exception:
            log.exception("handle_record failed (attempt %d)", attempt + 1)
            time.sleep(min(2 ** attempt, 30))
    _to_dlq(record)
    return True


def _to_dlq(record: Record) -> None:  # pragma: no cover
    c = get_config()
    headers = {**record.headers, "error": "max retries exceeded"}
    get_producer().send(c.kafka_dlq_topic, record.key, record.value, headers)
    log.error("record sent to DLQ (%s)", record.headers.get("trace_id"))
