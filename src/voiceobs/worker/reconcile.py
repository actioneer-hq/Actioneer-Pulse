"""Pull-path audio backfill, provider-agnostic. For each agent with audio analysis enabled, use its
storage descriptor + driver to list the configured store and register any settled recording whose
Call has no audio yet — extracting the call id (= OTLP trace_id) from each object key via the
descriptor's `key_regex`, and mapping the filename to a Media.kind via `file_map`.

The store is the source of truth; the artifact POST is just a latency optimization on top."""

from __future__ import annotations

import logging
import re
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.config import get_config
from voiceobs.db.models import AgentAudioConfig, Call, Media, Tombstone
from voiceobs.db.session import get_session, org_schema_keys, use_org_schema
from voiceobs.storage import ResolvedStorage, resolve_storage

session_scope = contextmanager(get_session)
log = logging.getLogger(__name__)

GRACE_S = get_config().reconcile_grace_s


def reconcile(db: Session, grace_s: float = GRACE_S) -> int:
    """Register every settled, unregistered recording across all audio-enabled agents."""
    cutoff = datetime.now(UTC) - timedelta(seconds=grace_s)
    backfilled = 0
    for cfg in db.scalars(select(AgentAudioConfig).where(AgentAudioConfig.enabled.is_(True))):
        st = resolve_storage(db, cfg.agent_id)
        if st is None:
            continue
        backfilled += _reconcile_agent(db, cfg.agent_id, st, cutoff)
    return backfilled


def _reconcile_agent(db: Session, agent_id: str, st: ResolvedStorage, cutoff: datetime) -> int:
    """List via the driver, then match each key against the descriptor to extract call_id + kind."""
    try:
        objects = st.driver.list(st.descriptor, st.creds)
    except Exception as e:  # noqa: BLE001 — one agent's bad bucket must not stall the rest
        log.warning("reconcile: list failed for agent %s: %s", agent_id, e)
        return 0
    key_re = re.compile(st.descriptor["key_regex"])
    id_group = st.descriptor.get("id_group", "call_id")
    file_map: dict = st.descriptor.get("file_map", {})  # filename -> Media.kind
    base = f"{st.driver.scheme}://{st.descriptor['bucket']}/"
    n = 0
    for uri, modified in objects:
        if _aware(modified) > cutoff:
            continue
        kind = file_map.get(uri.rsplit("/", 1)[-1])
        if kind is None:
            continue
        m = key_re.search(uri.removeprefix(base))  # regex is over the key (bucket-relative)
        if not m:
            continue
        call_id = m.groupdict().get(id_group)
        if call_id and _register(db, agent_id, call_id, uri, kind):
            n += 1
    return n


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
