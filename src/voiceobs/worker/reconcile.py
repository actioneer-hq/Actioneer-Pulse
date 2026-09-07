"""Pull-path audio backfill. For each agent with audio analysis enabled, scan its configured
S3 bucket/prefix and register any settled recording whose Call has no audio yet — matching on
the call_id (= OTLP trace_id) embedded in the key:

    s3://<bucket>/<prefix>/<call_id>/audio.wav            (stereo), or
    s3://<bucket>/<prefix>/<call_id>/audio_caller.wav + audio_agent.wav

S3 is the source of truth; the artifact POST is just a latency optimization on top."""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.config import get_config
from voiceobs.db.models import AgentAudioConfig, Call, Media, Tombstone
from voiceobs.db.session import get_session, org_schema_keys, use_org_schema
from voiceobs.storage import list_objects, resolve_s3_creds

session_scope = contextmanager(get_session)
log = logging.getLogger(__name__)

GRACE_S = get_config().reconcile_grace_s

# filename -> Media.kind (what the worker's _audio_bytes looks for)
_KINDS = {"audio.wav": "audio", "audio_caller.wav": "audio_caller", "audio_agent.wav": "audio_agent"}


def reconcile(db: Session, grace_s: float = GRACE_S) -> int:
    """Register every settled, unregistered recording across all audio-enabled agents."""
    cutoff = datetime.now(UTC) - timedelta(seconds=grace_s)
    backfilled = 0
    for cfg in db.scalars(select(AgentAudioConfig).where(AgentAudioConfig.enabled.is_(True))):
        if not cfg.s3_bucket:
            continue
        backfilled += _reconcile_agent(db, cfg, cutoff)
    return backfilled


def _reconcile_agent(db: Session, cfg: AgentAudioConfig, cutoff: datetime) -> int:
    prefix = (cfg.s3_prefix or "").strip("/")
    base = f"s3://{cfg.s3_bucket}/{prefix}".rstrip("/")
    creds = resolve_s3_creds(db, cfg.agent_id)
    n = 0
    try:
        objects = list_objects(base + "/", creds)
    except Exception as e:  # noqa: BLE001 — one agent's bad bucket must not stall the rest
        log.warning("reconcile: list failed for agent %s: %s", cfg.agent_id, e)
        return 0
    for uri, modified in objects:
        kind = _KINDS.get(uri.rsplit("/", 1)[-1])
        if kind is None or _aware(modified) > cutoff:
            continue
        call_id = _parse_call_id(uri, cfg.s3_bucket, prefix)
        if call_id and _register(db, cfg.agent_id, call_id, uri, kind):
            n += 1
    return n


def _parse_call_id(uri: str, bucket: str, prefix: str) -> str | None:
    """The <call_id> directory in `<prefix>/<call_id>/<file>`, relative to the configured prefix."""
    key = uri.removeprefix(f"s3://{bucket}/")
    if prefix:
        key = key.removeprefix(prefix.strip("/") + "/")
    parts = [p for p in key.split("/") if p]
    return parts[0] if len(parts) >= 2 else None  # <call_id>/<file>


def _register(db: Session, agent_id: str, call_id: str, uri: str, kind: str) -> bool:
    call = db.scalar(
        select(Call).where(Call.agent_id == agent_id, Call.external_call_id == call_id)
    )
    if call is None:
        return False  # spans never arrived either — nothing to attach audio to yet
    if db.get(Tombstone, call_id) is not None:
        return False
    if db.scalar(select(Media).where(Media.call_id == call.id, Media.kind == kind)):
        return False  # already registered (POST won, or a prior reconcile)

    db.add(Media(call_id=call.id, kind=kind, uri=uri))
    call.media_ready = True
    if call.spans_complete:
        call.status = "ingested"
    return True


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _run_once() -> None:  # pragma: no cover
    with session_scope() as db:
        for org in org_schema_keys(db):  # sweep each org's schema (one flat schema on SQLite)
            use_org_schema(db, org)
            log.info("reconciled %s: %d recording(s)", org, reconcile(db))


def main() -> None:  # pragma: no cover — entrypoint
    """One-shot, or a sidecar loop when VOICEOBS_RECONCILE_INTERVAL_S is set."""
    interval = get_config().reconcile_interval_s
    if not interval:
        _run_once()
        return
    while True:
        _run_once()
        time.sleep(interval)


if __name__ == "__main__":  # pragma: no cover
    main()
