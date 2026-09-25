"""Azure Blob Storage driver — the one mainstream store that doesn't speak the S3 API (its own REST
+ Shared-Key/SAS auth). Lazy-imports azure-storage-blob (the `azure` optional extra).

Creds dict (any one auth path):
- account_name + account_key            (Shared Key; enables SAS presign)
- connection_string                     (full connection string)
- account_name + sas_token              (pre-made SAS; presign just re-appends it)
Optional `account_url` overrides the default `https://{account}.blob.core.windows.net` (Azurite/custom).

Object uris are `azblob://<container>/<blob>`. `descriptor.bucket` is the container name."""

from __future__ import annotations

from datetime import datetime

from voiceobs.config import get_config
from voiceobs.util import assert_public_endpoint


def _account_url(creds: dict) -> str:
    if creds.get("account_url"):
        return creds["account_url"]
    return f"https://{creds['account_name']}.blob.core.windows.net"


def _service_client(creds: dict):
    from azure.storage.blob import BlobServiceClient

    if creds.get("connection_string"):
        return BlobServiceClient.from_connection_string(creds["connection_string"])
    url = _account_url(creds)
    # SSRF guard on a tenant-supplied account_url (Azurite/custom); opt out via config.
    assert_public_endpoint(url, enabled=get_config().block_internal_fetch)
    credential = creds.get("account_key") or creds.get("sas_token")
    return BlobServiceClient(account_url=url, credential=credential)


def _parse(uri: str) -> tuple[str, str]:
    rest = uri.removeprefix("azblob://")
    container, _, blob = rest.partition("/")
    return container, blob


class AzureDriver:
    scheme = "azblob"

    def list(self, descriptor: dict, creds: dict) -> list[tuple[str, datetime]]:
        container = descriptor["bucket"]
        prefix = (descriptor.get("list_prefix") or "").lstrip("/")
        cc = _service_client(creds).get_container_client(container)
        return [(f"azblob://{container}/{b.name}", b.last_modified)
                for b in cc.list_blobs(name_starts_with=prefix)]

    def fetch_bytes(self, uri: str, creds: dict | None) -> bytes:
        container, blob = _parse(uri)
        bc = _service_client(creds or {}).get_blob_client(container, blob)
        return bc.download_blob().readall()

    def presign(self, uri: str, creds: dict | None, expires_s: int = 900) -> str:
        from datetime import UTC, timedelta

        from azure.storage.blob import BlobSasPermissions, generate_blob_sas

        creds = creds or {}
        container, blob = _parse(uri)
        base = f"{_account_url(creds)}/{container}/{blob}"
        if creds.get("sas_token"):  # already a SAS — just attach it
            return f"{base}?{creds['sas_token'].lstrip('?')}"
        sas = generate_blob_sas(
            account_name=creds["account_name"], container_name=container, blob_name=blob,
            account_key=creds["account_key"], permission=BlobSasPermissions(read=True),
            expiry=datetime.now(UTC) + timedelta(seconds=expires_s),
        )
        return f"{base}?{sas}"
