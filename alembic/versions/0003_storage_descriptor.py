"""agent_audio_config: provider-agnostic storage descriptor + dynamic creds

Replaces the fixed S3 columns with a provider tag + JSON descriptor + credential field-spec +
non-secret cred values + an encrypted secret blob. Runs per schema (see alembic/env.py). Greenfield
— no data backfill. Uses batch_alter_table so the DROP/ADD works on both Postgres and SQLite.

Revision ID: 0003_storage_descriptor
Revises: 0002_conv_call_id
Create Date: 2026-09-08
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0003_storage_descriptor"
down_revision = "0002_conv_call_id"
branch_labels = None
depends_on = None

_DROP = ["s3_bucket", "s3_prefix", "s3_region", "s3_endpoint_url",
         "access_key_id", "secret_ciphertext"]
_ADD = [
    ("provider", sa.String(32)), ("descriptor", sa.JSON()), ("cred_spec", sa.JSON()),
    ("cred_public", sa.JSON()), ("cred_secret_ciphertext", sa.Text()),
]


def _cols(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    # Idempotent: the create_all baseline already builds the current-model columns on a fresh DB,
    # so only add what's missing / drop what's present.
    have = _cols("agent_audio_config")
    with op.batch_alter_table("agent_audio_config") as b:
        for name, type_ in _ADD:
            if name not in have:
                b.add_column(sa.Column(name, type_, nullable=True))
        for col in _DROP:
            if col in have:
                b.drop_column(col)


def downgrade() -> None:
    with op.batch_alter_table("agent_audio_config") as b:
        b.add_column(sa.Column("s3_bucket", sa.String(255), nullable=True))
        b.add_column(sa.Column("s3_prefix", sa.String(1024), nullable=True))
        b.add_column(sa.Column("s3_region", sa.String(64), nullable=True))
        b.add_column(sa.Column("s3_endpoint_url", sa.String(512), nullable=True))
        b.add_column(sa.Column("access_key_id", sa.String(128), nullable=True))
        b.add_column(sa.Column("secret_ciphertext", sa.Text(), nullable=True))
        for col in ["cred_secret_ciphertext", "cred_public", "cred_spec", "descriptor", "provider"]:
            b.drop_column(col)
