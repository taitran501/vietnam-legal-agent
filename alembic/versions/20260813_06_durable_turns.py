"""add durable conversation turn lifecycle

Revision ID: 20260813_06
Revises: 20260812_05
"""

import sqlalchemy as sa
from alembic import op

revision = "20260813_06"
down_revision = "20260812_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("messages") as batch:
        batch.add_column(sa.Column("turn_id", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("status", sa.String(length=32), nullable=False, server_default="complete"))
        batch.add_column(sa.Column("superseded_by_message_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
        batch.create_index("ix_messages_turn_id", ["turn_id"])

    op.create_table(
        "conversation_turns",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("conversation_id", sa.String(length=128), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(length=128), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("replay_metadata", sa.JSON(), nullable=False),
        sa.Column("user_message_id", sa.Integer(), nullable=True),
        sa.Column("assistant_message_id", sa.Integer(), nullable=False),
        sa.Column("target_assistant_message_id", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_conversation_turns_conversation_id", "conversation_turns", ["conversation_id"])
    op.create_index("ix_conversation_turns_user_id", "conversation_turns", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_conversation_turns_user_id", table_name="conversation_turns")
    op.drop_index("ix_conversation_turns_conversation_id", table_name="conversation_turns")
    op.drop_table("conversation_turns")
    with op.batch_alter_table("messages") as batch:
        batch.drop_index("ix_messages_turn_id")
        batch.drop_column("updated_at")
        batch.drop_column("superseded_by_message_id")
        batch.drop_column("status")
        batch.drop_column("turn_id")
