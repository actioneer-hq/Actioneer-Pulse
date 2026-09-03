"""Auth building blocks: password hashing, the password provider, signed sessions, the
provider registry, and ingest-token mint/resolve."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from voiceobs.auth import (
    hash_password,
    issue_session,
    mint_ingest_token,
    provider_for,
    read_session,
    resolve_ingest_token,
)
from voiceobs.auth.password import verify_password
from voiceobs.db import Base
from voiceobs.db.models import Agent, AppUser, Organization


def _db() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_password_hash_roundtrip():
    h = hash_password("s3cret")
    assert verify_password(h, "s3cret")
    assert not verify_password(h, "wrong")


def test_password_provider_authenticates_and_normalizes_email():
    db = _db()
    db.add(AppUser(id="u1", email="a@b.com", password_hash=hash_password("pw"), is_active=True))
    db.commit()
    p = provider_for("password")
    assert p is not None
    assert p.authenticate(db, {"email": "A@B.com ", "password": "pw"}).id == "u1"  # normalized
    assert p.authenticate(db, {"email": "a@b.com", "password": "nope"}) is None
    assert p.authenticate(db, {"email": "missing@b.com", "password": "pw"}) is None


def test_inactive_user_cannot_authenticate():
    db = _db()
    db.add(AppUser(id="u2", email="x@y.com", password_hash=hash_password("pw"), is_active=False))
    db.commit()
    assert provider_for("password").authenticate(db, {"email": "x@y.com", "password": "pw"}) is None


def test_session_roundtrip_and_rejects_tampering(monkeypatch):
    monkeypatch.setenv("VOICEOBS_SECRET_KEY", "test-secret")
    tok = issue_session("u42")
    assert read_session(tok) == "u42"
    assert read_session(None) is None
    assert read_session("garbage.not.signed") is None
    # a different secret must not validate the cookie
    monkeypatch.setenv("VOICEOBS_SECRET_KEY", "another-secret")
    assert read_session(tok) is None


def test_ingest_token_mint_resolve_and_revoke():
    db = _db()
    db.add(Organization(id="o1", name="O", slug="o1"))
    db.add(Agent(id="ag1", org_id="o1", name="A", slug="a"))
    db.commit()
    plain, row = mint_ingest_token(db, "o1", "ag1")
    db.commit()
    assert plain.startswith("vo_")
    assert resolve_ingest_token(db, plain) == ("o1", "ag1")
    assert resolve_ingest_token(db, "vo_deadbeef_bogus") is None
    assert resolve_ingest_token(db, "not-a-token") is None
    row.revoked_at = datetime.now(UTC)
    db.commit()
    assert resolve_ingest_token(db, plain) is None


def test_registry_has_password_provider():
    assert provider_for("password") is not None
    assert provider_for("nope") is None
