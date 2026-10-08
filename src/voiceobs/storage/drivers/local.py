"""Upload store: `upload://<org>/<agent>/<job>/<name>` objects live in the org's `upload_blob` table.

File onboarding writes the manifest and call audio here; the api, the workers and playback read it
back through the same `fetch_bytes(uri)` path as S3/Azure. The DB is the only thing every service
shares — a local disk is not (each Railway service has its own). Uris from before the move still
resolve to files under `Config.upload_dir` as a fallback."""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.config import get_config
from voiceobs.db.models import UploadBlob
from voiceobs.db.session import get_session, use_org_schema

SCHEME = "upload"


def upload_root() -> Path:
    return Path(get_config().upload_dir).resolve()


def key_of(uri: str) -> str:
    """The blob key of an `upload://` uri; refuse anything that is not a plain relative key."""
    if not uri.startswith(f"{SCHEME}://"):
        raise ValueError(f"not an upload uri: {uri}")
    key = uri.removeprefix(f"{SCHEME}://")
    if not key or key.startswith("/") or "\\" in key or ".." in key.split("/"):
        raise ValueError(f"invalid upload uri: {uri}")
    return key


def uri_for(key: str) -> str:
    return f"{SCHEME}://{key}"


def path_for(uri: str) -> Path:
    """Legacy: resolve an `upload://` uri to a file under the upload root."""
    root = upload_root()
    p = (root / key_of(uri)).resolve()
    if os.path.commonpath([root, p]) != str(root):
        raise ValueError(f"upload uri escapes the upload root: {uri}")
    return p


def put_blob(db: Session, key: str, data: bytes) -> str:
    """Store one upload object in the session's org schema (flushed and released at once, so a
    big ZIP never sits in the session whole). Returns its uri."""
    blob = UploadBlob(key=key, data=data, bytes=len(data))
    db.add(blob)
    db.flush()
    db.expunge(blob)
    return uri_for(key)


def get_blob(db: Session, key: str) -> bytes | None:
    return db.scalar(select(UploadBlob.data).where(UploadBlob.key == key))


def blob_keys(db: Session, prefix: str) -> list[str]:
    return list(db.scalars(select(UploadBlob.key).where(UploadBlob.key.startswith(prefix, autoescape=True))
                           .order_by(UploadBlob.key)))


@contextmanager
def _org_session(key: str):
    """A session pointed at the org schema named by the key's first segment."""
    gen = get_session()
    db = next(gen)
    try:
        use_org_schema(db, key.split("/", 1)[0])
        yield db
    finally:
        gen.close()


class LocalDriver:
    scheme = SCHEME

    def list(self, descriptor: dict, creds: dict) -> list[tuple[str, datetime]]:
        prefix = descriptor.get("prefix", "").strip("/")
        if not prefix:
            return []
        with _org_session(prefix) as db:
            rows = db.execute(select(UploadBlob.key, UploadBlob.created_at)
                              .where(UploadBlob.key.startswith(prefix + "/", autoescape=True))).all()
        return [(uri_for(k), at) for k, at in rows]

    def fetch_bytes(self, uri: str, creds: dict | None) -> bytes:
        key = key_of(uri)
        with _org_session(key) as db:
            data = get_blob(db, key)
        if data is None:
            data = path_for(uri).read_bytes()  # uploaded before the move to the DB
        return data

    def presign(self, uri: str, creds: dict | None, expires_s: int = 900) -> str:
        raise NotImplementedError("upload:// objects are served through the API audio proxy")
