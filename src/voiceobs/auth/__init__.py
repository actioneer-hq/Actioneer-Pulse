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
from voiceobs.auth.password import PasswordProvider, hash_password, normalize_email
from voiceobs.auth.registry import provider_for, providers, register_provider
from voiceobs.auth.session import (
    COOKIE_NAME,
    MAX_AGE_S,
    issue_invite,
    issue_session,
    read_invite,
    read_session,
)
from voiceobs.auth.tokens import mint_ingest_token, resolve_ingest_token

# Register the shipped providers (import side-effect, like frameworks/__init__.py).
register_provider(PasswordProvider())

__all__ = [
    "COOKIE_NAME",
    "MAX_AGE_S",
    "PasswordProvider",
    "current_membership",
    "current_user",
    "get_scoped_call",
    "hash_password",
    "issue_invite",
    "issue_session",
    "mint_ingest_token",
    "normalize_email",
    "provider_for",
    "providers",
    "read_invite",
    "read_session",
    "register_provider",
    "require_role",
    "resolve_ingest_token",
    "visible_agent_ids",
]
