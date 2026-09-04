"""Deployment-mode helpers shared by auth + ingest."""

from __future__ import annotations

from voiceobs.settings import get_settings

# The seeded dev account. Used by `python -m voiceobs.auth bootstrap` under dev-open and
# surfaced by GET /v1/auth/config so the login form prefills for a one-click sign-in. These
# are only ever exposed / created when dev_open() is true — never in a real deployment.
DEV_EMAIL = "dev@actioneer.local"
DEV_PASSWORD = "actioneer-dev"  # not a real credential; dev-only seed default


def dev_open() -> bool:
    """True in a source checkout / test run: VOICEOBS_DEV_OPEN is set, or the DB is SQLite.
    Gates the session-secret fallback and the token-less ingest fallback — NEVER true in a
    real Postgres deployment unless explicitly asked for."""
    return get_settings().is_dev_open
