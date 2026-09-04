"""chat: conversation + chat_message for the global-chat agent.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: str | Sequence[str] | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("app_user.id")),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_conversation_owner", "conversation", ["tenant_id", "created_by"])
    op.create_table(
        "chat_message",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversation.id"), nullable=False),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("steps", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("conversation_id", "seq", name="uq_chat_message_seq"),
    )
    op.create_index("ix_chat_message_conv", "chat_message", ["conversation_id", "seq"])


def downgrade() -> None:
    op.drop_index("ix_chat_message_conv", table_name="chat_message")
    op.drop_table("chat_message")
    op.drop_index("ix_conversation_owner", table_name="conversation")
    op.drop_table("conversation")
