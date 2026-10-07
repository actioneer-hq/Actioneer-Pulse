"""The journey-llm worker: journey stages 2 (LLM enrichment) and 3 (training-data curation).

Stage 1 (the decision model, in the judge worker) lands in seconds and queues stage 2; stage 2 queues
stage 3 when the call has a failure to correct. Both backfill here, off the judging path. Enrichment is
drained before curation (it's what the UI waits on). Scale with `--scale journey-llm=N`. At-least-once:
offsets commit after the DB commit; both stages are idempotent. Poison records go to the DLQ."""

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
from voiceobs.judge.queue import decode_judge, enqueue_stage

log = logging.getLogger(__name__)
session_scope = contextmanager(get_session)


def handle(db, stage: str, record: Record) -> bool:
    """Run `stage` for one queued call. Returns True when stage 3 should be queued (after enrich)."""
    from voiceobs.judge.journey_stages import curate_call, enrich_call

    org, call_id = decode_judge(record)
    use_org_schema(db, org)
    call = db.scalar(select(Call).where(Call.external_call_id == call_id))
    if call is None:
        log.warning("journey-llm: call %s not found (org=%s) — skipping", call_id, org)
        return False
    if stage == "enrich":
        return enrich_call(db, call)
    curate_call(db, call)
    return False


def main() -> None:  # pragma: no cover — the long-running consumer loop
    logging.basicConfig(level=get_config().log_level)
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    c = get_config()
    enrich = get_consumer(c.kafka_journey_group, [c.kafka_topic_enrich])
    curate = get_consumer(c.kafka_journey_group, [c.kafka_topic_curate])
    log.info("journey-llm worker up (enrich=%s curate=%s)", c.kafka_topic_enrich, c.kafka_topic_curate)
    try:
        while not stopping:
            stage, consumer, record = "enrich", enrich, enrich.poll(0.2)
            if record is None:
                stage, consumer, record = "curate", curate, curate.poll(0.5)  # only when enrich is drained
            if record is not None and _consume_one(stage, record):
                consumer.commit(record)
    finally:
        enrich.close()
        curate.close()
    log.info("journey-llm worker down")


def _consume_one(stage: str, record: Record) -> bool:  # pragma: no cover
    for attempt in range(get_config().kafka_max_retries):
        try:
            with session_scope() as db:
                then_curate = handle(db, stage, record)
            if then_curate:
                org, call_id = decode_judge(record)
                enqueue_stage(get_producer(), "curate", org, call_id)
            return True
        except Exception:
            log.exception("journey-llm %s failed (attempt %d)", stage, attempt + 1)
            time.sleep(min(2 ** attempt, 30))
    c = get_config()
    get_producer().send(c.kafka_journey_dlq, record.key, record.value,
                        {**record.headers, "stage": stage, "error": "max retries exceeded"})
    log.error("journey-llm record sent to DLQ (%s)", record.key)
    return True


if __name__ == "__main__":  # pragma: no cover
    main()
