"""Identity + auth. Modular by design: an `AuthProvider` proves who you are, a
provider-agnostic signed-cookie session keeps you in, and `current_user`/`current_membership`
+ RBAC deps gate everything. Only the email/password provider ships in v1; SSO/OIDC/BYO
register alongside it later with no changes to call sites.

`auth` may import `db`; `core`/`frameworks` must NOT import `auth` (import-linter).
"""

from __future__ import annotations

from voiceobs.auth.deps import (
    current_membership,
    current_user,
    get_scoped_call,
    require_role,
    visible_agent_ids,
)
from voiceobs.auth.jwt import decode_invite, encode_access, encode_invite
from voiceobs.auth.password import PasswordProvider, hash_password, normalize_email
from voiceobs.auth.refresh import (
    mint_refresh,
    revoke_all,
    revoke_refresh,
    rotate_refresh,
)
from voiceobs.auth.registry import provider_for, providers, register_provider
from voiceobs.auth.session import (
    ACCESS_COOKIE,
    ACCESS_MAX_AGE_S,
    COOKIE_NAME,
    CSRF_COOKIE,
    REFRESH_COOKIE,
    REFRESH_MAX_AGE_S,
    REFRESH_PATH,
    issue_access,
    read_access,
)
from voiceobs.auth.tokens import mint_ingest_token, resolve_ingest_token

# Register the shipped providers (import side-effect, like frameworks/__init__.py).
register_provider(PasswordProvider())

__all__ = [
    "ACCESS_COOKIE",
    "ACCESS_MAX_AGE_S",
    "COOKIE_NAME",
    "CSRF_COOKIE",
    "REFRESH_COOKIE",
    "REFRESH_MAX_AGE_S",
    "REFRESH_PATH",
    "PasswordProvider",
    "current_membership",
    "current_user",
    "decode_invite",
    "encode_access",
    "encode_invite",
    "get_scoped_call",
    "hash_password",
    "issue_access",
    "mint_ingest_token",
    "mint_refresh",
    "normalize_email",
    "provider_for",
    "providers",
    "read_access",
    "register_provider",
    "require_role",
    "resolve_ingest_token",
    "revoke_all",
    "revoke_refresh",
    "rotate_refresh",
    "visible_agent_ids",
]
