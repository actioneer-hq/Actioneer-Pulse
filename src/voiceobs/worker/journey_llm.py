"""The journey-llm worker: training-data curation for judged calls whose project turned it on.

The judge (decision model + LLM) queues a call here when it has failed agent turns to correct; this
worker rewrites them (one LLM call per call) into `training_sample`. Off the judging path, so it never
slows judging down. Scale with `--scale journey-llm=N`. At-least-once: offsets commit after the DB commit;
curation is idempotent. Poison records go to the DLQ."""

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
from voiceobs.judge.queue import decode_judge

log = logging.getLogger(__name__)
session_scope = contextmanager(get_session)


def handle(db, record: Record) -> int:
    """Curate one queued call. Returns how many training samples were stored."""
    from voiceobs.judge.journey_stages import curate_call

    org, call_id = decode_judge(record)
    use_org_schema(db, org)
    call = db.scalar(select(Call).where(Call.external_call_id == call_id))
    if call is None:
        log.warning("journey-llm: call %s not found (org=%s) — skipping", call_id, org)
        return 0
    return curate_call(db, call)


def main() -> None:  # pragma: no cover — the long-running consumer loop
    logging.basicConfig(level=get_config().log_level)
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    c = get_config()
    consumer = get_consumer(c.kafka_journey_group, [c.kafka_topic_curate])
    log.info("journey-llm worker up (curate=%s)", c.kafka_topic_curate)
    try:
        while not stopping:
            record = consumer.poll(0.5)
            if record is not None and _consume_one(record):
                consumer.commit(record)
    finally:
        consumer.close()
    log.info("journey-llm worker down")


def _consume_one(record: Record) -> bool:  # pragma: no cover
    for attempt in range(get_config().kafka_max_retries):
        try:
            with session_scope() as db:
                handle(db, record)
            return True
        except Exception:
            log.exception("journey-llm curate failed (attempt %d)", attempt + 1)
            time.sleep(min(2 ** attempt, 30))
    c = get_config()
    get_producer().send(c.kafka_journey_dlq, record.key, record.value,
                        {**record.headers, "error": "max retries exceeded"})
    log.error("journey-llm record sent to DLQ (%s)", record.key)
    return True


if __name__ == "__main__":  # pragma: no cover
    main()
