"""Dialect-aware column types.

`Embedding` stores an embedding vector as a real pgvector `vector` on Postgres (so `<=>` cosine
queries work) and as packed little-endian float32 `LargeBinary` on SQLite (dev/tests, no pgvector).
Clustering reads the value back as a plain `list[float]` on either dialect."""

from __future__ import annotations

import struct

from sqlalchemy.types import LargeBinary, TypeDecorator


class Embedding(TypeDecorator):
    """A vector column: pgvector on Postgres, float32 blob elsewhere. Dimensionless (BYO models vary);
    a fixed-dim HNSW index is added in the similarity-search phase, not here."""

    impl = LargeBinary
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector
            return dialect.type_descriptor(Vector())
        return dialect.type_descriptor(LargeBinary())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return list(value)  # pgvector's Vector impl formats the list into a vector literal
        return struct.pack(f"<{len(value)}f", *value)  # sqlite: packed float32

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return list(value)  # pgvector returns a numpy array
        return list(struct.unpack(f"<{len(value) // 4}f", value))
