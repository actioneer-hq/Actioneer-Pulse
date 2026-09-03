"""Per-agent ingest tokens (Sentry-DSN style). Plaintext `vo_<prefix>_<secret>` is shown
once at mint; only its argon2 hash is stored. Resolving = prefix lookup (indexed) then
argon2-verify, so we never scan every token."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.db.models import IngestToken

_ph = PasswordHasher()
_PREFIX_LEN = 8  # hex chars


def mint_ingest_token(
    db: Session, org_id: str, agent_id: str, name: str | None = None
) -> tuple[str, IngestToken]:
    """Returns (plaintext, row). The plaintext is the ONLY time the secret exists in the
    clear — the caller must hand it to the user once and never store it."""
    prefix = secrets.token_hex(_PREFIX_LEN // 2)
    secret = secrets.token_urlsafe(32)
    plaintext = f"vo_{prefix}_{secret}"
    row = IngestToken(
        org_id=org_id, agent_id=agent_id, token_prefix=prefix,
        token_hash=_ph.hash(plaintext), name=name,
    )
    db.add(row)
    return plaintext, row


def resolve_ingest_token(db: Session, plaintext: str | None) -> tuple[str, str] | None:
    """(org_id, agent_id) for a valid, non-revoked token; else None. Stamps last_used_at."""
    if not plaintext or not plaintext.startswith("vo_"):
        return None
    parts = plaintext.split("_", 2)
    if len(parts) < 3:
        return None
    prefix = parts[1]
    rows = db.scalars(
        select(IngestToken).where(
            IngestToken.token_prefix == prefix, IngestToken.revoked_at.is_(None)
        )
    )
    for row in rows:
        try:
            _ph.verify(row.token_hash, plaintext)
        except (VerifyMismatchError, InvalidHashError):
            continue
        row.last_used_at = datetime.now(UTC)
        return row.org_id, row.agent_id
    return None
