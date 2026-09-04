"""Deployment-mode helpers shared by auth + ingest."""

from __future__ import annotations

import os

_TRUE = ("1", "true", "on", "yes")


def dev_open() -> bool:
    """True in a source checkout / test run: VOICEOBS_DEV_OPEN is set, or the DB is SQLite.
    Gates the session-secret fallback and the token-less ingest fallback — NEVER true in a
    real Postgres deployment unless explicitly asked for."""
    if os.getenv("VOICEOBS_DEV_OPEN", "").strip().lower() in _TRUE:
        return True
    return os.getenv("VOICEOBS_DATABASE_URL", "").startswith("sqlite")
