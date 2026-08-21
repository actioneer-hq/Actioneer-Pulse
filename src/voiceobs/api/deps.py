"""Shared API dependencies. session_dep is patched in tests to a SQLite session."""

from __future__ import annotations

from datetime import UTC, datetime

from voiceobs.db.session import get_session

# Indirection so tests can override the DB without touching db.session internals.
session_dep = get_session


def now() -> datetime:
    return datetime.now(UTC)
