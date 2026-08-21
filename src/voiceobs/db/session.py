"""Engine + session factory. Shared by the API and (later) the worker."""

from __future__ import annotations

import os
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

_engine = None
_Session: sessionmaker[Session] | None = None


def _init() -> None:
    global _engine, _Session
    url = os.environ["VOICEOBS_DATABASE_URL"]
    _engine = create_engine(url, future=True)
    _Session = sessionmaker(bind=_engine, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency — one session per request, committed on clean exit."""
    if _Session is None:
        _init()
    assert _Session is not None
    session = _Session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
