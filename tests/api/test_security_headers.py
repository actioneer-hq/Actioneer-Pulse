"""LOW-1: security response headers on every response; HSTS only over HTTPS."""

from __future__ import annotations


def test_headers_present(client):
    r = client.get("/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


def test_hsts_only_on_https(client):
    assert "Strict-Transport-Security" not in client.get("/health").headers  # http test client


def test_hsts_present_over_https(db_sessionmaker):
    from fastapi.testclient import TestClient

    from voiceobs.api.app import app
    with TestClient(app, base_url="https://testserver") as https:
        assert "Strict-Transport-Security" in https.get("/health").headers
