"""A stable, anonymous per-install id. No PII, no hostname — a random UUID.

Resolution order: VOICEOBS_INSTALL_ID env / config override → a file under ~/.voiceobs/ → an ephemeral
random id (used when the file can't be persisted, e.g. a container with no mounted volume; this only
causes slight install over-counting, never a failure). Set VOICEOBS_INSTALL_ID or mount the dir for
stable counts."""

from __future__ import annotations

import os
import uuid
from functools import lru_cache
from pathlib import Path

from voiceobs.config import get_config


def _path() -> Path:
    root = os.environ.get("VOICEOBS_STATE_DIR") or str(Path.home() / ".voiceobs")
    return Path(root) / "install_id"


@lru_cache(maxsize=1)
def install_id() -> str:
    override = os.environ.get("VOICEOBS_INSTALL_ID") or get_config().install_id
    if override:
        return override
    path = _path()
    try:
        if path.exists():
            existing = path.read_text().strip()
            if existing:
                return existing
        path.parent.mkdir(parents=True, exist_ok=True)
        value = uuid.uuid4().hex
        path.write_text(value)
        return value
    except OSError:
        return uuid.uuid4().hex  # ephemeral — never let telemetry identity break anything
