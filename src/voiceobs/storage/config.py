"""Resolve a per-agent storage config into a driver + descriptor + credential dict. The one place
the worker and read API decrypt creds, so decryption lives in exactly one spot. Credentials are a
dynamic set (whatever the field-spec declared): non-secret values in `cred_public`, secret values in
the Fernet blob `cred_secret_ciphertext` — merged here into one dict for the driver."""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.auth.crypto import decrypt
from voiceobs.db.models import AgentAudioConfig
from voiceobs.storage.drivers import StorageDriver, get_driver


@dataclass(frozen=True)
class ResolvedStorage:
    provider: str
    descriptor: dict
    creds: dict
    driver: StorageDriver


def audio_config(db: Session, agent_id: str | None) -> AgentAudioConfig | None:
    if not agent_id:
        return None
    return db.scalar(select(AgentAudioConfig).where(AgentAudioConfig.agent_id == agent_id))


def _creds_dict(cfg: AgentAudioConfig) -> dict:
    creds = dict(cfg.cred_public or {})
    secret = decrypt(cfg.cred_secret_ciphertext)
    if secret:
        creds.update(json.loads(secret))
    return creds


def resolve_storage(db: Session, agent_id: str | None) -> ResolvedStorage | None:
    """The driver + descriptor + creds for an ENABLED, fully-configured agent, else None."""
    cfg = audio_config(db, agent_id)
    if cfg is None or not cfg.enabled or not cfg.provider or not cfg.descriptor:
        return None
    return ResolvedStorage(cfg.provider, cfg.descriptor, _creds_dict(cfg), get_driver(cfg.provider))


def resolve_creds(db: Session, agent_id: str | None) -> dict | None:
    """Just the credential dict for an agent (for fetch/presign of an already-stored uri), or None
    → the driver falls back to its default credential chain."""
    cfg = audio_config(db, agent_id)
    if cfg is None:
        return None
    return _creds_dict(cfg) or None
