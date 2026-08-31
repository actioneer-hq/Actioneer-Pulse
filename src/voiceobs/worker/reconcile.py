"""Backfill audio the artifact POST never delivered. S3 is the source of truth:
the POST is a latency optimization, this is the guarantee.

Scans the recordings prefix and, for any WAV whose Call has no audio Media row,
registers it — the same effect as POST /v1/calls/{id}/artifacts, minus the caller."""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.db.models import Call, Media, Tombstone
from voiceobs.db.session import get_session
from voiceobs.storage import list_objects

session_scope = contextmanager(get_session)

log = logging.getLogger(__name__)

GRACE_S = float(os.getenv("VOICEOBS_RECONCILE_GRACE_S", "600"))


def reconcile(db: Session, prefix: str, grace_s: float = GRACE_S) -> int:
    """Register every settled, unregistered WAV under `prefix`. Returns the count."""
    cutoff = datetime.now(UTC) - timedelta(seconds=grace_s)
    backfilled = 0
    for uri, modified in list_objects(prefix):
        if not uri.endswith(".wav") or _aware(modified) > cutoff:
            continue
        ident = _parse_key(uri)
        if ident is None:
            continue
        tenant, call_id = ident
        if _register(db, tenant, call_id, uri):
            backfilled += 1
    return backfilled


def _register(db: Session, tenant: str, call_id: str, uri: str) -> bool:
    if db.get(Tombstone, {"tenant_id": tenant, "call_id": call_id}) is not None:
        return False
    call = db.scalar(
        select(Call).where(Call.tenant_id == tenant, Call.external_call_id == call_id)
    )
    if call is None:
        return False  # spans never arrived either — nothing to attach audio to yet
    if db.scalar(select(Media).where(Media.call_id == call.id, Media.kind == "audio")):
        return False  # already registered (POST won, or a prior reconcile)

    db.add(Media(call_id=call.id, tenant_id=tenant, kind="audio", uri=uri))
    call.media_ready = True
    if call.spans_complete:
        call.status = "ingested"
    return True


def _parse_key(uri: str) -> tuple[str, str] | None:
    """tenant + call_id from the recordings layout
    voice/{tenant}/{app}/{campaign}/{recipient}/{call_id}/audio.wav."""
    parts = uri.removeprefix("s3://").split("/")
    parts = [p for p in parts[1:] if p]  # drop bucket
    if len(parts) < 3 or parts[0] != "voice":
        return None
    return parts[1], parts[-2]


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def main() -> None:  # pragma: no cover — entrypoint
    prefix = os.environ["VOICEOBS_RECORDINGS_PREFIX"]
    with session_scope() as db:
        n = reconcile(db, prefix)
    log.info("reconciled %d call(s)", n)


if __name__ == "__main__":  # pragma: no cover
    main()
