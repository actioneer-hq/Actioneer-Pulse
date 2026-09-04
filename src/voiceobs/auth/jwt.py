"""Access + invite JWTs (PyJWT, HS256). Signed with VOICEOBS_SECRET_KEY.

Access tokens are short-lived and STATELESS — verifying one is a signature check, no DB hit.
Revocation is not their job; that lives on the refresh token (auth/refresh.py). We pin the
algorithm to HS256 on both encode and decode, which sidesteps the JWT alg-confusion class of
bugs (a token claiming `alg:none`/RS256 is simply rejected)."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt

from voiceobs.auth.env import dev_open

_ALG = "HS256"
_DEV_SECRET = "dev-insecure-secret-do-not-use-in-prod"

ACCESS_TTL = timedelta(minutes=15)
REFRESH_TTL = timedelta(days=14)
INVITE_TTL = timedelta(days=7)


def _secret() -> str:
    secret = os.getenv("VOICEOBS_SECRET_KEY")
    if secret:
        return secret
    if dev_open():
        return _DEV_SECRET
    raise RuntimeError("VOICEOBS_SECRET_KEY must be set (no dev fallback outside dev-open)")


def _encode(claims: dict, ttl: timedelta, token_type: str) -> str:
    now = datetime.now(UTC)
    payload = {
        **claims,
        "type": token_type,
        "iat": now,
        "exp": now + ttl,
        "jti": uuid4().hex,
    }
    return jwt.encode(payload, _secret(), algorithm=_ALG)


def _decode(token: str | None, token_type: str) -> dict | None:
    """Validated claims for a token of the expected type, else None (bad sig / expired /
    wrong type). Never raises — callers treat None as unauthenticated."""
    if not token:
        return None
    try:
        claims = jwt.decode(token, _secret(), algorithms=[_ALG])
    except jwt.InvalidTokenError:
        return None
    return claims if claims.get("type") == token_type else None


def encode_access(user_id: str) -> str:
    return _encode({"sub": user_id}, ACCESS_TTL, "access")


def decode_access(token: str | None) -> str | None:
    """The user id a valid, unexpired access token carries, else None."""
    claims = _decode(token, "access")
    return claims.get("sub") if claims else None


def encode_invite(user_id: str) -> str:
    return _encode({"sub": user_id}, INVITE_TTL, "invite")


def decode_invite(token: str | None) -> str | None:
    claims = _decode(token, "invite")
    return claims.get("sub") if claims else None
