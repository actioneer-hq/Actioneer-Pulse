"""The closed event catalog. Every event name maps to the exact set of dimension keys it may carry —
the client drops anything not listed, so no free-form/PII dimension can ever be sent.

Dimensions must be aggregate product signals only: never tenant/org names, endpoints, tokens, call
content, transcripts, metric values, or file paths."""

from __future__ import annotations

SCHEMA_VERSION = 1
APP = "pulse"

# event name -> allowed dimension keys
CATALOG: dict[str, set[str]] = {
    # periodic "this install is alive" + version distribution
    "deploy.heartbeat": {"version"},
    # which adapter ran + which optional features are on; counts are bucketed ranges, not raw values
    "feature.used": {"adapter", "audio", "backfill", "chat", "judge", "calls_bucket"},
    # an anonymized failure signal — a reason code only, never the payload/message
    "error.occurred": {"reason", "where"},
    # an agent onboarded via the wizard: what market use-case it serves + its framework/language.
    # use_case is a short, non-identifying descriptor (the wizard/skill guarantees no names/PII).
    "agent.configured": {"use_case", "framework", "language"},
}


def allowed_dims(name: str) -> set[str] | None:
    return CATALOG.get(name)
