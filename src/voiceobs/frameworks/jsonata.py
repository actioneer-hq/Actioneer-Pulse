"""A data-driven OTLP adapter: one JSONata expression -> canonical Trace.

Unlike the code adapters (livekit/vas/generic), the dialect knowledge here is DATA — a JSONata
expression authored per agent by the Pulse wizard and stored in `AgentOtlpMapping`. The expression
maps the producer's raw OTLP payload onto Pulse's canonical `Trace` JSON
(`{header: {...}, spans: [...]}`); constructing the `Trace` from that output validates it (stage enum,
field types, required fields) for free.

Pure: takes the expression string, no DB import. The worker resolves the mapping
(`mapping.resolve_mapping`) and constructs this. `jsonata` is imported lazily so api/ingest — which
never adapt payloads — don't need the dependency."""

from __future__ import annotations

from voiceobs.core.model import Trace
from voiceobs.frameworks.base import UnsupportedSchema


class JSONataAdapter:
    name = "jsonata"

    def __init__(self, expression: str, version: int = 1) -> None:
        self._expr = expression
        self.version = version

    def matches(self, payload: dict) -> bool:
        # Selected explicitly by tenant (a registered mapping wins); matching is unused.
        return True

    def to_trace(self, payload: dict) -> Trace:
        import jsonata  # lazy: only the analysis service needs it

        try:
            out = jsonata.Jsonata(self._expr).evaluate(payload)
        except Exception as e:  # a bad expression/eval must quarantine the call, not crash the worker
            raise UnsupportedSchema(f"jsonata mapping failed: {e}") from e
        if not isinstance(out, dict):
            raise UnsupportedSchema("jsonata mapping did not produce a Trace object")
        try:
            return Trace.model_validate(out)
        except Exception as e:
            raise UnsupportedSchema(f"jsonata output is not a valid Trace: {e}") from e
