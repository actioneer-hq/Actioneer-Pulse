"""Symmetric encryption for secrets at rest (S3 keys today; judge api_key can adopt it).

Fernet with a key derived from VOICEOBS_SECRET_KEY — so the same secret that signs sessions
also protects stored credentials, and rotating it invalidates both (a deliberate, documented
coupling). Ciphertext is a urlsafe-base64 token; `encrypt`/`decrypt` are inverse."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from voiceobs.settings import get_settings

_DEV_SECRET = "dev-insecure-secret-do-not-use-in-prod"


def _secret() -> str:
    s = get_settings()
    if s.secret_key:
        return s.secret_key
    if s.is_dev_open:
        return _DEV_SECRET
    raise RuntimeError("VOICEOBS_SECRET_KEY must be set (no dev fallback outside dev-open)")


def _fernet() -> Fernet:
    # Fernet needs a 32-byte urlsafe-base64 key; derive one deterministically from the secret.
    key = base64.urlsafe_b64encode(hashlib.sha256(_secret().encode()).digest())
    return Fernet(key)


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(blob: str | None) -> str | None:
    """Plaintext for a ciphertext produced by `encrypt`, or None if absent/undecryptable
    (e.g. the secret key was rotated) — callers treat None as "no usable credential"."""
    if not blob:
        return None
    try:
        return _fernet().decrypt(blob.encode()).decode()
    except (InvalidToken, ValueError):
        return None
