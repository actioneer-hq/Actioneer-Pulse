"""The message bus between ingest and analysis — a thin Producer/Consumer seam so the transport is
swappable (Kafka in prod; an in-memory double in tests) and a future Go ingest speaks the same
contract. Mirrors the `storage/drivers` pattern: Protocols here, Kafka impl lazy-imported, test
double injectable.

Contract (topic `raw-spans`, from config): key = call_id else trace_id; value = the gzipped OTLP
slice verbatim (byte-identical to what RawFragment stored); headers carry identity
(org, agent_id, call_id, trace_id, batch_id, seq, received_at, schema_version)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Record:
    """One message. `raw` is the driver's native handle (a Kafka Message) used for offset commit."""
    topic: str
    key: str | None
    value: bytes
    headers: dict[str, str] = field(default_factory=dict)
    raw: object | None = None


class Producer(Protocol):
    def send(self, topic: str, key: str | None, value: bytes, headers: dict[str, str]) -> None: ...
    def flush(self, timeout: float = 10.0) -> None: ...


class Consumer(Protocol):
    def poll(self, timeout: float = 1.0) -> Record | None: ...
    def commit(self, record: Record) -> None: ...
    def close(self) -> None: ...


# Test hooks (mirror ratelimit.set_client / storage overrides).
_producer_override: Producer | None = None
_consumer_factory_override = None


def set_producer(p: Producer | None) -> None:
    global _producer_override
    _producer_override = p


def set_consumer_factory(factory) -> None:
    global _consumer_factory_override
    _consumer_factory_override = factory


def get_producer() -> Producer:
    if _producer_override is not None:
        return _producer_override
    from voiceobs.bus.kafka import KafkaProducer
    return KafkaProducer()


def get_consumer(group: str | None = None, topics: list[str] | None = None) -> Consumer:
    if _consumer_factory_override is not None:
        return _consumer_factory_override(group, topics)
    from voiceobs.bus.kafka import KafkaConsumer
    return KafkaConsumer(group, topics)
