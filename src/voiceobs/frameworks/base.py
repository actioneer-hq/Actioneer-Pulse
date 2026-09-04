"""Framework interface + registry.

A *framework* is one voice-agent producer Pulse supports: an `Adapter` (its OTLP dialect →
normalized `Trace`) plus a `Calculator` (Trace → metrics). Most frameworks use the generic
`Calculator`; one is supplied only when the producer's timing model differs.

`core` never imports `frameworks` (import-linter); `frameworks` import `core`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from voiceobs.core.calculator import Calculator
from voiceobs.core.model import Trace


class UnsupportedSchema(Exception):
    """A payload an adapter matched but cannot turn into a Trace — a schema version it
    can't handle, or a batch with no call in it.

    Ingest maps this to the producer_schema_unsupported trust reason. Adapters raise it
    instead of crashing so one bad batch never takes the worker down."""


@runtime_checkable
class Adapter(Protocol):
    name: str
    version: int

    def matches(self, payload: dict) -> bool: ...
    def to_trace(self, payload: dict) -> Trace: ...


@dataclass(frozen=True)
class Framework:
    """A supported producer: its adapter (dialect) and calculator (metrics). The
    calculator defaults to the generic `Calculator` — override it only for a producer whose
    timing model the base can't express."""

    name: str
    adapter: Adapter
    calculator: Calculator = field(default_factory=Calculator)


_REGISTRY: list[Framework] = []


def register(fw: Framework) -> None:
    _REGISTRY.append(fw)


def register_adapter(adapter: Adapter) -> None:
    """Back-compat: register an adapter with the default Calculator."""
    register(Framework(name=adapter.name, adapter=adapter))


def framework_for(payload: dict) -> Framework | None:
    """First registered framework whose adapter matches, routed by the payload signature."""
    return next((f for f in _REGISTRY if f.adapter.matches(payload)), None)


def adapter_for(payload: dict) -> Adapter | None:
    """Back-compat shim: the matching framework's adapter, or None."""
    fw = framework_for(payload)
    return fw.adapter if fw else None
