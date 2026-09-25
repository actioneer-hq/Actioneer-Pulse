"""H3 regression: ingest body-size + decompression caps. H2: tenant regex length validated at write."""

from __future__ import annotations

import gzip
import json


def test_oversized_body_rejected(client, monkeypatch):
    monkeypatch.setenv("VOICEOBS_MAX_INGEST_BYTES", "100")
    r = client.post("/v1/traces", content=b"x" * 500,
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_gzip_bomb_rejected(client, monkeypatch):
    monkeypatch.setenv("VOICEOBS_MAX_INGEST_BYTES", str(10 * 1024 * 1024))
    monkeypatch.setenv("VOICEOBS_MAX_DECODED_BYTES", "1024")
    bomb = gzip.compress(b"\x00" * (2 * 1024 * 1024))  # decompresses far past the 1 KiB ceiling
    r = client.post("/v1/traces", content=bomb,
                    headers={"Content-Type": "application/json", "Content-Encoding": "gzip"})
    assert r.status_code == 413


def test_normal_gzip_body_still_accepted(client, monkeypatch):
    monkeypatch.setenv("VOICEOBS_MAX_DECODED_BYTES", str(1024 * 1024))
    body = gzip.compress(json.dumps({"resourceSpans": []}).encode())
    r = client.post("/v1/traces", content=body,
                    headers={"Content-Type": "application/json", "Content-Encoding": "gzip"})
    assert r.status_code == 200


def test_overlong_selector_regex_rejected_at_register(client, login_as):
    login_as("default")
    aid = client.post("/v1/agents", json={"name": "Bot"}).json()["id"]
    token = client.post(f"/v1/agents/{aid}/ingest-tokens", json={"name": "t"}).json()["token"]
    manifest = {
        "schema": "pulse.integration", "version": 1, "ingest_method": "storage_polling",
        "artifacts": [{"id": "a", "selector": {"object_path_regex": "a" * 1000}}],
        "mappers": {},
    }
    r = client.put("/v1/ingest/integration-manifest", json=manifest,
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 422
