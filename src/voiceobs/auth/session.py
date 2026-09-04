"""Stateless signed-cookie sessions. Provider-agnostic: once ANY provider verifies a user,
the endpoint mints a session here; the rest of the app only ever reads current_user.

Signed with VOICEOBS_SECRET_KEY via itsdangerous (purpose-built for signed cookies, no JWT
alg-confusion footgun). No Session table — logout clears the cookie; a revocation table is a
clean later add."""

from __future__ import annotations

import os

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from voiceobs.auth.env import dev_open

COOKIE_NAME = "vo_session"
MAX_AGE_S = 14 * 24 * 3600  # 14 days
_SALT = "vo-session"
_DEV_SECRET = "dev-insecure-secret-do-not-use-in-prod"


def _secret() -> str:
    secret = os.getenv("VOICEOBS_SECRET_KEY")
    if secret:
        return secret
    if dev_open():
        return _DEV_SECRET
    raise RuntimeError("VOICEOBS_SECRET_KEY must be set (no dev fallback outside dev-open)")


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_secret(), salt=_SALT)


def issue_session(user_id: str) -> str:
    return _serializer().dumps({"uid": user_id})


def read_session(cookie: str | None) -> str | None:
    """The user id a valid, unexpired cookie carries, else None."""
    if not cookie:
        return None
    try:
        data = _serializer().loads(cookie, max_age=MAX_AGE_S)
    except (BadSignature, SignatureExpired):
        return None
    return data.get("uid") if isinstance(data, dict) else None


_INVITE_SALT = "vo-invite"
INVITE_MAX_AGE_S = 7 * 24 * 3600


def issue_invite(user_id: str) -> str:
    """A signed, expiring invite token carrying the invited user's id."""
    return URLSafeTimedSerializer(_secret(), salt=_INVITE_SALT).dumps({"uid": user_id})


def read_invite(token: str | None) -> str | None:
    if not token:
        return None
    try:
        data = URLSafeTimedSerializer(_secret(), salt=_INVITE_SALT).loads(
            token, max_age=INVITE_MAX_AGE_S
        )
    except (BadSignature, SignatureExpired):
        return None
    return data.get("uid") if isinstance(data, dict) else None
