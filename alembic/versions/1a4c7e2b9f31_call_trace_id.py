"""call.trace_id — resolve later span batches back to the call whose root already arrived

Revision ID: 1a4c7e2b9f31
Revises: 0339d76df33c
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1a4c7e2b9f31"
down_revision: str | Sequence[str] | None = "0339d76df33c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("call", sa.Column("trace_id", sa.String(64), nullable=True))
    op.create_index("ix_call_trace_id", "call", ["trace_id"])
    op.create_index("ix_call_tenant_trace", "call", ["tenant_id", "trace_id"])


def downgrade() -> None:
    op.drop_index("ix_call_tenant_trace", table_name="call")
    op.drop_index("ix_call_trace_id", table_name="call")
    op.drop_column("call", "trace_id")
