"""Resolve a per-agent S3 credential from its audio config. The one place the worker and the
read API get the creds for fetch/presign, so decryption lives in exactly one spot."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.auth.crypto import decrypt
from voiceobs.db.models import AgentAudioConfig
from voiceobs.storage.fetch import S3Creds


def audio_config(db: Session, agent_id: str | None) -> AgentAudioConfig | None:
    if not agent_id:
        return None
    return db.scalar(select(AgentAudioConfig).where(AgentAudioConfig.agent_id == agent_id))


def resolve_s3_creds(db: Session, agent_id: str | None) -> S3Creds | None:
    """The decrypted S3 creds for an agent, or None (no config / no secret / undecryptable →
    fall back to boto3's default credential chain)."""
    cfg = audio_config(db, agent_id)
    if cfg is None or not cfg.access_key_id:
        return None
    secret = decrypt(cfg.secret_ciphertext)
    if not secret:
        return None
    return S3Creds(
        access_key_id=cfg.access_key_id,
        secret_access_key=secret,
        region=cfg.s3_region,
        endpoint_url=cfg.s3_endpoint_url,
    )
