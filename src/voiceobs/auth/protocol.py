"""The auth-provider strategy. One method: prove who you are, once. Everything after
(sessions, RBAC) is provider-agnostic — which is what makes SSO/BYO drop-in later.

Mirrors the frameworks/base.py Adapter protocol + registry shape."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from voiceobs.db.models import AppUser


@runtime_checkable
class AuthProvider(Protocol):
    name: str

    def authenticate(self, db: Session, credentials: dict) -> AppUser | None: ...
    def supports_signup(self) -> bool: ...
