"""Declarative base + column helpers. Generic JSON so the schema also stands up
on SQLite for tests (maps to jsonb on Postgres)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _uuid() -> str:
    return str(uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


def pk() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True, default=_uuid)


def created_col() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
