"""confluent-kafka (librdkafka) Producer/Consumer — the production transport. Lazy-imported (the
`kafka` extra) so the base install and the fast test suite stay broker-free. Sync, matching the
sync SQLAlchemy code. Manual offset commit only (`enable.auto.commit=false`) so the consumer can
commit AFTER the DB transaction (at-least-once; safe given idempotent writes)."""

from __future__ import annotations

from voiceobs.bus import Record
from voiceobs.config import get_config


def _brokers() -> str:
    b = get_config().kafka_brokers
    if not b:
        raise RuntimeError("VOICEOBS_KAFKA_BROKERS must be set (Kafka is the ingest→analysis transport)")
    return b


class KafkaProducer:
    def __init__(self) -> None:
        from confluent_kafka import Producer
        self._p = Producer({"bootstrap.servers": _brokers(), "enable.idempotence": True})

    def send(self, topic: str, key: str | None, value: bytes, headers: dict[str, str]) -> None:
        self._p.produce(
            topic, key=key.encode() if key else None, value=value,
            headers=[(k, str(v).encode()) for k, v in headers.items()],
        )
        self._p.poll(0)  # serve delivery callbacks without blocking the request

    def flush(self, timeout: float = 10.0) -> None:
        self._p.flush(timeout)


class KafkaConsumer:
    def __init__(self, group: str | None, topics: list[str] | None) -> None:
        from confluent_kafka import Consumer
        c = get_config()
        self._c = Consumer({
            "bootstrap.servers": _brokers(),
            "group.id": group or c.kafka_consumer_group,
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
        })
        self._c.subscribe(topics or [c.kafka_topic_raw])

    def poll(self, timeout: float = 1.0) -> Record | None:
        from confluent_kafka import KafkaException
        msg = self._c.poll(timeout)
        if msg is None:
            return None
        if msg.error():
            raise KafkaException(msg.error())
        headers = {k: (v.decode() if isinstance(v, bytes | bytearray) else v)
                   for k, v in (msg.headers() or [])}
        return Record(
            topic=msg.topic(), key=msg.key().decode() if msg.key() else None,
            value=msg.value(), headers=headers, raw=msg,
        )

    def commit(self, record: Record) -> None:
        self._c.commit(record.raw, asynchronous=False)

    def close(self) -> None:
        self._c.close()
