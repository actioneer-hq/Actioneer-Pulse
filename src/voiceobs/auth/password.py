"""Email + password auth — the only provider shipped in v1. argon2 hashing.

Adding SSO/OIDC/trusted-header later = a new provider class registered alongside this one
(see registry.py); nothing else changes because the session/current_user layer is
provider-agnostic."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.db.models import AppUser

_ph = PasswordHasher()


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(hashed: str, password: str) -> bool:
    try:
        _ph.verify(hashed, password)
        return True
    except (VerifyMismatchError, InvalidHashError):
        return False


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


class PasswordProvider:
    name = "password"

    def supports_signup(self) -> bool:
        return True

    def authenticate(self, db: Session, credentials: dict) -> AppUser | None:
        email = normalize_email(credentials.get("email", ""))
        password = credentials.get("password") or ""
        user = db.scalar(select(AppUser).where(AppUser.email == email))
        if user is None or not user.is_active or not user.password_hash:
            return None
        if not verify_password(user.password_hash, password):
            return None
        return user
