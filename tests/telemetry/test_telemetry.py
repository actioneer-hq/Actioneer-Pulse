"""Telemetry client: opt-out gating, catalog filtering, deterministic batching, best-effort posting."""

from __future__ import annotations

import json

import pytest

from voiceobs.telemetry import client as tc
from voiceobs.telemetry.catalog import APP, SCHEMA_VERSION
from voiceobs.telemetry.install import install_id


@pytest.fixture(autouse=True)
def _reset():
    tc._reset_for_tests()
    install_id.cache_clear()
    yield
    tc._reset_for_tests()
    install_id.cache_clear()


def _enable(monkeypatch, endpoint="https://t.example/ingest"):
    monkeypatch.delenv("DO_NOT_TRACK", raising=False)
    monkeypatch.delenv("VOICEOBS_TELEMETRY_DISABLED", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("VOICEOBS_TELEMETRY_ENDPOINT", endpoint)
    monkeypatch.setenv("VOICEOBS_TELEMETRY_ENABLED", "true")


def test_disabled_without_endpoint(monkeypatch):
    monkeypatch.delenv("VOICEOBS_TELEMETRY_ENDPOINT", raising=False)
    monkeypatch.delenv("CI", raising=False)
    posts = _capture(monkeypatch)
    tc.emit("deploy.heartbeat", version="x")
    tc.flush()
    assert posts == []  # no endpoint → inert, no thread, no send


def test_do_not_track_disables(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    posts = _capture(monkeypatch)
    tc.emit("deploy.heartbeat", version="x")
    tc.flush()
    assert posts == []


def test_ci_disables(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setenv("CI", "true")
    posts = _capture(monkeypatch)
    tc.emit("deploy.heartbeat", version="x")
    tc.flush()
    assert posts == []


def test_emits_only_catalog_dims_and_builds_envelope(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setenv("VOICEOBS_INSTALL_ID", "fixed-install")
    posts = _capture(monkeypatch)
    # 'secret' is not in the catalog for feature.used → must be dropped
    tc.emit("feature.used", adapter="livekit", audio=True, secret="LEAK")
    tc.flush()

    assert len(posts) == 1
    env = posts[0]
    assert env["app"] == APP and env["schemaVersion"] == SCHEMA_VERSION
    assert env["installId"] == "fixed-install"
    assert env["batchId"]  # content hash present
    (event,) = env["events"]
    assert event["name"] == "feature.used"
    assert event["dims"] == {"adapter": "livekit", "audio": True}  # 'secret' stripped


def test_unknown_event_is_refused(monkeypatch):
    _enable(monkeypatch)
    posts = _capture(monkeypatch)
    tc.emit("totally.unknown", anything="x")
    tc.flush()
    assert posts == []


def test_post_failure_never_raises(monkeypatch):
    _enable(monkeypatch)

    def boom(*_a, **_k):
        raise OSError("network down")

    monkeypatch.setattr(tc.urllib.request, "urlopen", boom)
    tc.emit("deploy.heartbeat", version="x")
    tc.flush()  # must not raise


def _capture(monkeypatch) -> list[dict]:
    """Intercept urlopen and record the posted envelopes."""
    posts: list[dict] = []

    class _Resp:
        def close(self):
            pass

    def fake_urlopen(req, timeout=None):
        posts.append(json.loads(req.data.decode()))
        return _Resp()

    monkeypatch.setattr(tc.urllib.request, "urlopen", fake_urlopen)
    return posts
