"""Revocable refresh tokens — the stateful half of the session. The rotating plaintext
`vor_<prefix>_<secret>` lives only in the httpOnly refresh cookie; only its argon2 hash is
stored. Resolve = prefix lookup (indexed) then argon2-verify.

Rotation: each successful refresh revokes the presented token and mints a new one in the same
`family`. Reuse detection: presenting an already-revoked (or unknown-but-well-formed) token in a
family revokes the WHOLE family — the standard response to a stolen refresh token."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from voiceobs.auth.jwt import REFRESH_TTL
from voiceobs.db.models import RefreshToken

_ph = PasswordHasher()
_PREFIX_LEN = 8  # hex chars


def _now() -> datetime:
    return datetime.now(UTC)


def mint_refresh(
    db: Session, user_id: str, *, family_id: str | None = None, user_agent: str | None = None
) -> tuple[str, RefreshToken]:
    """Returns (plaintext, row). The plaintext is the only time the secret is in the clear."""
    prefix = secrets.token_hex(_PREFIX_LEN // 2)
    secret = secrets.token_urlsafe(32)
    plaintext = f"vor_{prefix}_{secret}"
    row = RefreshToken(
        user_id=user_id,
        family_id=family_id or uuid4().hex,
        token_prefix=prefix,
        token_hash=_ph.hash(plaintext),
        expires_at=_now() + REFRESH_TTL,
        user_agent=user_agent,
    )
    db.add(row)
    return plaintext, row


def _find(db: Session, plaintext: str | None) -> RefreshToken | None:
    """The row whose hash matches this plaintext (any state), by prefix lookup + verify."""
    if not plaintext or not plaintext.startswith("vor_"):
        return None
    parts = plaintext.split("_", 2)
    if len(parts) < 3:
        return None
    for row in db.scalars(
        select(RefreshToken).where(RefreshToken.token_prefix == parts[1])
    ):
        try:
            _ph.verify(row.token_hash, plaintext)
        except (VerifyMismatchError, InvalidHashError):
            continue
        return row
    return None


def _revoke_family(db: Session, family_id: str) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


def rotate_refresh(
    db: Session, plaintext: str | None, *, user_agent: str | None = None
) -> tuple[str, str] | None:
    """Verify + rotate. Returns (new_plaintext, user_id) or None if invalid/expired. A revoked
    token being presented is treated as theft: the whole family is revoked and None returned."""
    row = _find(db, plaintext)
    if row is None:
        return None
    if row.revoked_at is not None:  # reuse of a rotated/revoked token → kill the family
        _revoke_family(db, row.family_id)
        return None
    # SQLite hands back tz-naive datetimes; treat a naive value as UTC for the comparison.
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= _now():
        return None
    row.revoked_at = _now()
    row.last_used_at = _now()
    new_plaintext, _ = mint_refresh(
        db, row.user_id, family_id=row.family_id, user_agent=user_agent
    )
    return new_plaintext, row.user_id


def revoke_refresh(db: Session, plaintext: str | None) -> None:
    """Logout: revoke just the presented token (a no-op if it's unknown)."""
    row = _find(db, plaintext)
    if row is not None and row.revoked_at is None:
        row.revoked_at = _now()


def revoke_all(db: Session, user_id: str) -> int:
    """Logout everywhere: revoke every live refresh token for the user. Returns the count."""
    result = db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    return result.rowcount or 0
