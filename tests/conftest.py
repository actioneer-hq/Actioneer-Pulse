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
def authed_client(client, db_sessionmaker) -> TestClient:
    """A `client` already signed in as an owner of the default org (id="default"), with the
    session cookie set. Existing read/settings/judge tests use this once those endpoints
    require auth."""
    from voiceobs.auth import COOKIE_NAME, hash_password, issue_session
    from voiceobs.db.models import AppUser, Membership, Organization

    with db_sessionmaker() as db:
        db.add(AppUser(id="u-owner", email="owner@test.co",
                       password_hash=hash_password("pw"), is_active=True))
        db.add(Organization(id="default", name="Default", slug="default"))
        db.flush()
        db.add(Membership(id="m-owner", org_id="default", user_id="u-owner", role="owner"))
        db.commit()
    client.cookies.set(COOKIE_NAME, issue_session("u-owner"))
    return client
