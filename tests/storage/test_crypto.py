"""Secret encryption at rest (Fernet keyed off VOICEOBS_SECRET_KEY)."""

from __future__ import annotations

from voiceobs.auth.crypto import decrypt, encrypt


def test_encrypt_decrypt_roundtrip(monkeypatch):
    monkeypatch.setenv("VOICEOBS_SECRET_KEY", "test-secret")
    blob = encrypt("AKIA-super-secret")
    assert blob != "AKIA-super-secret"       # actually encrypted
    assert decrypt(blob) == "AKIA-super-secret"


def test_decrypt_none_and_garbage():
    assert decrypt(None) is None
    assert decrypt("not-a-fernet-token") is None


def test_rotating_the_key_makes_old_ciphertext_undecryptable(monkeypatch):
    monkeypatch.setenv("VOICEOBS_SECRET_KEY", "key-one")
    blob = encrypt("s3cret")
    monkeypatch.setenv("VOICEOBS_SECRET_KEY", "key-two")
    assert decrypt(blob) is None  # wrong key → None, never a wrong plaintext
