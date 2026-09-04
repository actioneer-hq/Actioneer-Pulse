"""TestClient over an in-memory SQLite DB, with session_dep overridden."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from voiceobs.api.app import app
from voiceobs.api.deps import session_dep
from voiceobs.db import Base


@pytest.fixture
def db_sessionmaker() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def client(db_sessionmaker) -> Iterator[TestClient]:
    def _session() -> Iterator[Session]:
        s = db_sessionmaker()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    app.dependency_overrides[session_dep] = _session
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _dev_open(monkeypatch) -> None:
    """Tests run in dev-open: token-less ingest falls back to the default org, and the
    session cookie uses the dev secret. Mirrors a local source checkout."""
    monkeypatch.setenv("VOICEOBS_DEV_OPEN", "1")


@pytest.fixture
def login_as(client, db_sessionmaker):
    """Sign `client` in as a member of `org_id` with `role`, seeding the org/user/membership
    on demand. Returns the same client (cookie set). Call it as the org a test's calls
    belong to — e.g. `login_as("vastu-hfc")` for sample_call data."""
    from sqlalchemy import select

    from voiceobs.auth import ACCESS_COOKIE, hash_password, issue_access
    from voiceobs.db.models import AppUser, Membership, Organization

    def _login(org_id: str = "default", role: str = "owner") -> TestClient:
        uid = f"u-{org_id}-{role}"
        with db_sessionmaker() as db:
            if db.get(AppUser, uid) is None:
                db.add(AppUser(id=uid, email=f"{uid}@test.co",
                               password_hash=hash_password("pw"), is_active=True))
            if db.get(Organization, org_id) is None:
                db.add(Organization(id=org_id, name=org_id, slug=org_id))
            db.flush()
            has = db.scalar(select(Membership).where(
                Membership.org_id == org_id, Membership.user_id == uid))
            if has is None:
                db.add(Membership(org_id=org_id, user_id=uid, role=role))
            db.commit()
        client.cookies.set(ACCESS_COOKIE, issue_access(uid))
        return client

    return _login


@pytest.fixture
def authed_client(login_as) -> TestClient:
    """Signed in as an owner of the default org."""
    return login_as("default")
