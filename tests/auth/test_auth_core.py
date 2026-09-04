"""Auth building blocks: password hashing, the password provider, signed sessions, the
provider registry, and ingest-token mint/resolve."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from voiceobs.auth import (
    hash_password,
    issue_access,
    mint_ingest_token,
    mint_refresh,
    provider_for,
    read_access,
    resolve_ingest_token,
    revoke_all,
    rotate_refresh,
)
from voiceobs.auth.password import verify_password
from voiceobs.db import Base
from voiceobs.db.models import Agent, AppUser, Organization, RefreshToken


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


def test_access_jwt_roundtrip_and_rejects_tampering(monkeypatch):
    monkeypatch.setenv("VOICEOBS_SECRET_KEY", "test-secret")
    tok = issue_access("u42")
    assert read_access(tok) == "u42"
    assert read_access(None) is None
    assert read_access("garbage.not.a.jwt") is None
    # a different secret must not validate the token (HS256 signature check)
    monkeypatch.setenv("VOICEOBS_SECRET_KEY", "another-secret")
    assert read_access(tok) is None


def test_access_jwt_rejects_expired(monkeypatch):

    from voiceobs.auth import jwt as vjwt
    monkeypatch.setenv("VOICEOBS_SECRET_KEY", "test-secret")
    monkeypatch.setattr(vjwt, "ACCESS_TTL", timedelta(seconds=-1))  # already expired
    assert read_access(vjwt.encode_access("u1")) is None


def test_access_jwt_rejects_wrong_type(monkeypatch):
    from voiceobs.auth import jwt as vjwt
    monkeypatch.setenv("VOICEOBS_SECRET_KEY", "test-secret")
    invite = vjwt.encode_invite("u1")            # a valid token, wrong type
    assert read_access(invite) is None           # access decode must reject it
    assert vjwt.decode_invite(invite) == "u1"    # but invite decode accepts it


def test_refresh_rotate_expiry_and_reuse_detection(monkeypatch):
    monkeypatch.setenv("VOICEOBS_SECRET_KEY", "test-secret")
    db = _db()
    db.add(AppUser(id="u9", email="r@x.com", password_hash=hash_password("pw"), is_active=True))
    db.commit()

    plain, row = mint_refresh(db, "u9")
    db.commit()
    fam = row.family_id

    # rotate: old token dies, a new one issues in the same family
    rotated = rotate_refresh(db, plain)
    assert rotated is not None
    new_plain, uid = rotated
    assert uid == "u9" and new_plain != plain
    db.commit()

    # reusing the ORIGINAL (now-rotated) token is theft → whole family revoked, incl. the new one
    assert rotate_refresh(db, plain) is None
    db.commit()
    assert rotate_refresh(db, new_plain) is None  # family was killed

    # garbage / unknown tokens are simply rejected
    assert rotate_refresh(db, "vor_deadbeef_bogus") is None
    assert rotate_refresh(db, "not-a-token") is None
    assert fam  # sanity


def test_refresh_revoke_all(monkeypatch):
    monkeypatch.setenv("VOICEOBS_SECRET_KEY", "test-secret")
    db = _db()
    db.add(AppUser(id="u10", email="a@a.com", password_hash=hash_password("pw"), is_active=True))
    db.commit()
    p1, _ = mint_refresh(db, "u10")
    p2, _ = mint_refresh(db, "u10")
    db.commit()
    assert revoke_all(db, "u10") == 2
    db.commit()
    assert rotate_refresh(db, p1) is None
    assert rotate_refresh(db, p2) is None
    assert db.query(RefreshToken).filter(RefreshToken.revoked_at.isnot(None)).count() == 2


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
