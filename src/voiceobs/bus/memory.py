"""In-memory bus double for tests — implements the same Producer/Consumer contract with a plain
list per topic, so the 260+ unit tests never need a broker. `InMemoryBus` is both a `Producer`
(send) and a store you can `drain()` or attach a `MemoryConsumer` to."""

from __future__ import annotations

from voiceobs.bus import Record


class InMemoryBus:
    def __init__(self) -> None:
        self.topics: dict[str, list[Record]] = {}

    # Producer
    def send(self, topic: str, key: str | None, value: bytes, headers: dict[str, str]) -> None:
        self.topics.setdefault(topic, []).append(Record(topic, key, value, dict(headers)))

    def flush(self, timeout: float = 10.0) -> None:
        pass

    # Test helpers
    def records(self, topic: str) -> list[Record]:
        return list(self.topics.get(topic, []))

    def drain(self, topic: str) -> list[Record]:
        recs = self.topics.get(topic, [])
        self.topics[topic] = []
        return recs

    def consumer(self, topics: list[str]) -> MemoryConsumer:
        return MemoryConsumer(self, topics)


class MemoryConsumer:
    """Drains an InMemoryBus in order across the given topics; commit is a no-op."""
    def __init__(self, bus: InMemoryBus, topics: list[str]) -> None:
        self._bus = bus
        self._topics = list(topics)

    def poll(self, timeout: float = 1.0) -> Record | None:
        for t in self._topics:
            q = self._bus.topics.get(t)
            if q:
                return q.pop(0)
        return None

    def commit(self, record: Record) -> None:
        pass

    def close(self) -> None:
        pass
