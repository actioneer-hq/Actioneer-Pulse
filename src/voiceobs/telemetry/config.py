"""Whether anonymous usage telemetry is on, and where it goes.

Opt-out and privacy-first: disabled by DO_NOT_TRACK, VOICEOBS_TELEMETRY_DISABLED, CI, the config flag,
or simply having no endpoint configured (inert until a sink is set)."""

from __future__ import annotations

import os

from voiceobs.config import get_config

_TRUTHY = {"1", "true", "yes", "on"}


def _env_flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in _TRUTHY


def telemetry_enabled() -> bool:
    """On only when explicitly enabled, an endpoint exists, and no opt-out signal is set."""
    if _env_flag("DO_NOT_TRACK") or _env_flag("VOICEOBS_TELEMETRY_DISABLED") or _env_flag("CI"):
        return False
    c = get_config()
    return bool(c.telemetry_enabled and c.telemetry_endpoint)


def endpoint() -> str | None:
    return get_config().telemetry_endpoint
