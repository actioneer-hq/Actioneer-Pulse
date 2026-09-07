"""Session cookie names + TTLs, and thin aliases over the JWT layer. Provider-agnostic:
once ANY provider verifies a user, the endpoint mints an access JWT here; the rest of the app
only ever reads current_user.

The session is now a short-lived access JWT (auth/jwt.py) backed by a revocable refresh token
(auth/refresh.py) — no more single long-lived signed cookie. These aliases keep a stable
surface for callers/tests."""

from __future__ import annotations

from voiceobs.auth.jwt import (
    ACCESS_TTL,
    REFRESH_TTL,
    decode_access,
    decode_access_org,
    encode_access,
)

# httpOnly cookie names.
ACCESS_COOKIE = "vo_access"
REFRESH_COOKIE = "vo_refresh"
CSRF_COOKIE = "vo_csrf"
REFRESH_PATH = "/v1/auth"  # refresh cookie only rides auth calls

# Back-compat: deps/tests referenced COOKIE_NAME as "the session cookie" = the access cookie.
COOKIE_NAME = ACCESS_COOKIE

ACCESS_MAX_AGE_S = int(ACCESS_TTL.total_seconds())
REFRESH_MAX_AGE_S = int(REFRESH_TTL.total_seconds())


def issue_access(user_id: str, org: str = "default") -> str:
    """Mint an access JWT for this user (the value of the vo_access cookie). `org` is the user's
    org slug, which selects the schema the request runs against."""
    return encode_access(user_id, org)


def read_access(cookie: str | None) -> str | None:
    """The user id a valid, unexpired access cookie carries, else None."""
    return decode_access(cookie)


def read_access_org(cookie: str | None) -> str | None:
    """The org slug a valid access cookie carries, else None."""
    return decode_access_org(cookie)
