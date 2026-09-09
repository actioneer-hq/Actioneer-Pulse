"""Per-chat audio-native toggle: availability reflects build-time config; the flag persists."""

from __future__ import annotations


def test_availability_false_without_key(authed_client):
    r = authed_client.post("/v1/chat/conversations")
    body = r.json()
    assert body["audio_native_enabled"] is False          # default off
    assert body["audio_native_available"] is False         # no key configured in tests


def test_availability_true_with_key(authed_client, monkeypatch):
    monkeypatch.setenv("VOICEOBS_AUDIO_NATIVE_API_KEY", "sk-audio")
    cid = authed_client.post("/v1/chat/conversations").json()["id"]
    assert authed_client.get(f"/v1/chat/conversations/{cid}").json()["audio_native_available"] is True


def test_toggle_persists(authed_client):
    cid = authed_client.post("/v1/chat/conversations").json()["id"]
    r = authed_client.patch(f"/v1/chat/conversations/{cid}", json={"audio_native_enabled": True})
    assert r.status_code == 200
    assert r.json()["audio_native_enabled"] is True
    # persisted across reads
    assert authed_client.get(f"/v1/chat/conversations/{cid}").json()["audio_native_enabled"] is True
    # and can be turned back off
    authed_client.patch(f"/v1/chat/conversations/{cid}", json={"audio_native_enabled": False})
    assert authed_client.get(f"/v1/chat/conversations/{cid}").json()["audio_native_enabled"] is False


def test_toggle_persists_even_when_unavailable(authed_client):
    # persisting the intent is allowed regardless of build-time availability; it just has no effect
    cid = authed_client.post("/v1/chat/conversations").json()["id"]
    r = authed_client.patch(f"/v1/chat/conversations/{cid}", json={"audio_native_enabled": True})
    assert r.json() == {"id": cid, "audio_native_enabled": True, "audio_native_available": False}
