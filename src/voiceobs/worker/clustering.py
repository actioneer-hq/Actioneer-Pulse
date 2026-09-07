"""Semantic-clustering sidecar. Embeds analysis prose and (re)clusters per tenant×lever, labelling
each cluster. One-shot by default; a loop when VOICEOBS_CLUSTER_INTERVAL_S is set. Run as
`python -m voiceobs.worker.clustering`. Best-effort — no-ops when no embedding model is configured."""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager

from voiceobs.clustering.service import recluster
from voiceobs.config import get_config
from voiceobs.db.session import get_session, org_schema_keys, use_org_schema

session_scope = contextmanager(get_session)
log = logging.getLogger(__name__)


def _run_once() -> None:  # pragma: no cover
    with session_scope() as db:
        for org in org_schema_keys(db):  # recluster each org's schema (one flat schema on SQLite)
            use_org_schema(db, org)
            log.info("clustering %s: %s", org, recluster(db))


def main() -> None:  # pragma: no cover — entrypoint
    logging.basicConfig(level=get_config().log_level)
    interval = get_config().cluster_interval_s
    if not interval:
        _run_once()
        return
    while True:
        _run_once()
        time.sleep(interval)


if __name__ == "__main__":  # pragma: no cover
    main()
