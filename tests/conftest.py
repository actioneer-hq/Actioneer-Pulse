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
from voiceobs.config import Config
from voiceobs.db import Base

# Tests must not read a developer's local .env (it would leak VOICEOBS_DEV_OPEN / a real
# DATABASE_URL into the suite). Disable dotenv loading for every Config() in tests.
Config.model_config["env_file"] = None


@pytest.fixture
def db_sessionmaker() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # the chat agent's curated views reference current_setting(...) — register the SQLite UDF so
    # the RBAC predicate works in tests exactly as it does via a Postgres GUC in prod.
    from voiceobs.db.session import _register_sqlite_udf
    _register_sqlite_udf(engine)
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
    # Streaming endpoints (chat SSE) open their own get_session() after the request dep closes —
    # point the module session at the same in-memory engine so they share this test's DB.
    import voiceobs.db.session as dbs
    saved = (dbs._engine, dbs._Session, dbs._AgentSession)
    # point both the main and the agent session at this test's engine (chat SQL runs on the agent
    # session; on SQLite it shares the main engine, which now carries the current_setting UDF).
    dbs._engine, dbs._Session = db_sessionmaker.kw["bind"], db_sessionmaker
    dbs._AgentSession = db_sessionmaker
    yield TestClient(app)
    dbs._engine, dbs._Session, dbs._AgentSession = saved
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _dev_open(monkeypatch) -> None:
    """Tests run in dev-open: token-less ingest falls back to the default org, and the
    session cookie uses the dev secret. Mirrors a local source checkout."""
    monkeypatch.setenv("VOICEOBS_DEV_OPEN", "1")


@pytest.fixture(autouse=True)
def bus():
    """Install an in-memory bus double as the producer for every test (ingest produces to it; no
    real Kafka). Request `bus` to inspect/drain produced records."""
    from voiceobs.bus import set_producer
    from voiceobs.bus.memory import InMemoryBus

    b = InMemoryBus()
    set_producer(b)
    yield b
    set_producer(None)


@pytest.fixture
def drain(bus, db_sessionmaker):
    """Consume the produced raw-spans through the analysis handler on the same in-memory DB —
    the produce→consume flow that replaces the old synchronous ingest write. Call after POSTing
    /v1/traces, then assert on the resulting Call/RawFragment/Turn rows."""
    from voiceobs.config import get_config
    from voiceobs.worker.run import handle_record

    def _drain() -> int:
        n = 0
        with db_sessionmaker() as db:
            for rec in bus.drain(get_config().kafka_topic_raw):
                handle_record(db, rec)
                n += 1
            db.commit()
        return n

    return _drain


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
