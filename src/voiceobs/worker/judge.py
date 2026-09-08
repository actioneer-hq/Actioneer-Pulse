"""The judge worker: drains the judge queue and runs the LLM judge at a bounded rate.

Judging is the throughput bottleneck (2 LLM calls per call), so it's decoupled from analysis: analysis/
backfill enqueue a {org, call_id} message, and this worker consumes it. The throttle is simply the
number of judge worker replicas (each single-flight) — scale with `--scale judge=N`; the gateway's
Retry-After backoff absorbs any residual 429s. Realtime is drained before backfill so a big backfill
never starves live judging. At-least-once: offsets commit after the DB commit; judge_call is idempotent
(it fetch-or-creates the Judgment row). Poison records go to the DLQ after bounded retries."""

from __future__ import annotations

import logging
import signal
import time
from contextlib import contextmanager

from sqlalchemy import select

from voiceobs.bus import Record, get_consumer, get_producer
from voiceobs.config import get_config
from voiceobs.db.models import Call
from voiceobs.db.session import get_session, use_org_schema
from voiceobs.judge import judge_call
from voiceobs.judge.queue import decode_judge

log = logging.getLogger(__name__)
session_scope = contextmanager(get_session)


def handle_judge(db, record: Record) -> None:
    """Judge one queued call within its org schema. Missing call = a no-op (erased/never persisted)."""
    org, call_id = decode_judge(record)
    use_org_schema(db, org)
    call = db.scalar(select(Call).where(Call.external_call_id == call_id))
    if call is None:
        log.warning("judge: call %s not found (org=%s) — skipping", call_id, org)
        return
    judge_call(db, call)


def main() -> None:  # pragma: no cover — the long-running consumer loop
    logging.basicConfig(level=get_config().log_level)
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    c = get_config()
    # Two consumers so realtime is strictly prioritized over backfill.
    realtime = get_consumer(c.kafka_judge_group, [c.kafka_topic_judge])
    backfill = get_consumer(c.kafka_judge_group, [c.kafka_topic_judge_backfill])
    log.info("judge worker up (realtime=%s backfill=%s group=%s)",
             c.kafka_topic_judge, c.kafka_topic_judge_backfill, c.kafka_judge_group)
    try:
        while not stopping:
            record = realtime.poll(0.2)
            consumer = realtime
            if record is None:
                record = backfill.poll(0.5)  # only when realtime is drained
                consumer = backfill
            if record is not None and _consume_one(record):
                consumer.commit(record)
    finally:
        realtime.close()
        backfill.close()
    log.info("judge worker down")


def _consume_one(record: Record) -> bool:  # pragma: no cover
    for attempt in range(get_config().kafka_max_retries):
        try:
            with session_scope() as db:
                handle_judge(db, record)
            return True
        except Exception:
            log.exception("handle_judge failed (attempt %d)", attempt + 1)
            time.sleep(min(2 ** attempt, 30))
    _to_dlq(record)
    return True


def _to_dlq(record: Record) -> None:  # pragma: no cover
    c = get_config()
    headers = {**record.headers, "error": "max retries exceeded"}
    get_producer().send(c.kafka_judge_dlq, record.key, record.value, headers)
    log.error("judge record sent to DLQ (%s)", record.key)


if __name__ == "__main__":  # pragma: no cover
    main()
