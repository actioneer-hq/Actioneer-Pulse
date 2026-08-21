"""Adapter interface + registry. One adapter per producer dialect; all yield Trace.

core never imports adapters (import-linter); adapters import core."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from voiceobs.core.model import Trace


class UnsupportedSchema(Exception):
    """A matched producer sent a schema version the adapter can't handle.

    Ingest maps this to the producer_schema_unsupported trust reason."""


@runtime_checkable
class Adapter(Protocol):
    name: str
    version: int

    def matches(self, payload: dict) -> bool: ...
    def to_trace(self, payload: dict) -> Trace: ...


_REGISTRY: list[Adapter] = []


def register_adapter(adapter: Adapter) -> None:
    _REGISTRY.append(adapter)


def adapter_for(payload: dict) -> Adapter | None:
    """First registered adapter that matches, routed by resource service.name."""
    return next((a for a in _REGISTRY if a.matches(payload)), None)
