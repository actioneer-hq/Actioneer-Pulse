"""Engine + session factory. Shared by the API and the worker.

Schema-per-tenant: each org lives in its own Postgres schema (`t_<slug>`) holding the whole table
set. A request/worker sets `search_path` to the active org's schema via `use_org_schema` before any
data access; all model queries then run unqualified against that schema. On SQLite (dev/tests) there
is a single flat schema, so `use_org_schema` is a no-op."""

from __future__ import annotations

import re
from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from voiceobs.config import get_config

_engine = None
_Session: sessionmaker[Session] | None = None
_agent_engine = None
_AgentSession: sessionmaker[Session] | None = None

DEFAULT_ORG = "default"


def _sanitize(slug: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", (slug or DEFAULT_ORG).lower())


def org_schema(slug: str) -> str:
    """The Postgres schema name for an org slug. Sanitized (identifiers are interpolated, so this
    must never contain anything but `[a-z0-9_]`)."""
    return f"t_{_sanitize(slug)}"


def ag_schema(slug: str) -> str:
    """The curated agent-view schema name for an org slug (the SQL agent's entire visible world)."""
    return f"ag_{_sanitize(slug)}"


def use_org_schema(session: Session, org_slug: str) -> None:
    """Point this session's connection at the org's schema. No-op on SQLite (single flat schema)."""
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return
    session.execute(text(f'SET search_path TO "{org_schema(org_slug)}"'))


def use_agent_schema(session: Session, org_slug: str) -> None:
    """Point the (agent-role) session at the org's curated view schema. No-op on SQLite."""
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return
    session.execute(text(f'SET search_path TO "{ag_schema(org_slug)}"'))


def org_schema_keys(session: Session) -> list[str]:
    """The org keys the worker must sweep, one per schema. On Postgres, every `t_*` org schema
    (returned as its slug key, ready for `use_org_schema`); on SQLite, the single flat schema."""
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return [DEFAULT_ORG]
    names = session.execute(text(
        r"SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE 't\_%'"
    )).scalars().all()
    return [n[2:] for n in names]  # strip the 't_' prefix -> the use_org_schema key


def _init() -> None:
    global _engine, _Session
    url = get_config().database_url
    if not url:
        raise RuntimeError("VOICEOBS_DATABASE_URL must be set")
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


def _init_agent() -> None:
    """Lazily build the agent engine. When agent_database_url is unset (SQLite/dev) the sandbox has
    no separate read-only role, so we fall back to the main engine."""
    global _agent_engine, _AgentSession
    url = get_config().agent_database_url
    if url:
        _agent_engine = create_engine(url, future=True)
        _AgentSession = sessionmaker(bind=_agent_engine, expire_on_commit=False)
    else:
        if _Session is None:
            _init()
        _AgentSession = _Session


def agent_session() -> Session:
    """A session on the read-only agent connection (pulse_agent_ro) if configured, else the main
    engine (dev). Caller is responsible for closing it."""
    if _AgentSession is None:
        _init_agent()
    assert _AgentSession is not None
    return _AgentSession()
