"""Local upload store: `upload://<relative path>` objects live under `Config.upload_dir`.

File onboarding writes uploaded call audio here (a disk volume shared by the api and the workers);
playback and analysis read it back through the same `fetch_bytes(uri)` path as S3/Azure."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from voiceobs.config import get_config

SCHEME = "upload"


def upload_root() -> Path:
    return Path(get_config().upload_dir).resolve()


def path_for(uri: str) -> Path:
    """Resolve an `upload://` uri to a file under the upload root; refuse anything that escapes it."""
    if not uri.startswith(f"{SCHEME}://"):
        raise ValueError(f"not an upload uri: {uri}")
    rel = uri.removeprefix(f"{SCHEME}://")
    if not rel or rel.startswith("/") or "\\" in rel:
        raise ValueError(f"invalid upload uri: {uri}")
    root = upload_root()
    p = (root / rel).resolve()
    if os.path.commonpath([root, p]) != str(root):
        raise ValueError(f"upload uri escapes the upload root: {uri}")
    return p


def uri_for(path: Path) -> str:
    """The `upload://` uri for a file already under the upload root."""
    rel = Path(path).resolve().relative_to(upload_root())
    return f"{SCHEME}://{rel.as_posix()}"


class LocalDriver:
    scheme = SCHEME

    def list(self, descriptor: dict, creds: dict) -> list[tuple[str, datetime]]:
        base = path_for(f"{SCHEME}://{descriptor.get('prefix', '').strip('/') or '.'}")
        return [(uri_for(p), datetime.fromtimestamp(p.stat().st_mtime, UTC))
                for p in base.rglob("*") if p.is_file()]

    def fetch_bytes(self, uri: str, creds: dict | None) -> bytes:
        return path_for(uri).read_bytes()

    def presign(self, uri: str, creds: dict | None, expires_s: int = 900) -> str:
        raise NotImplementedError("upload:// objects are served through the API audio proxy")
