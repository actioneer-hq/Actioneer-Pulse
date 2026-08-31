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
