"""add owner-scoped durable message feedback"""

import sqlalchemy as sa
from alembic import op

revision = "20260812_05"
down_revision = "20260810_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "message_feedback",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(length=128), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "conversation_id",
            sa.String(length=128),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_message_feedback_user_id", "message_feedback", ["user_id"])
    op.create_index("ix_message_feedback_conversation_id", "message_feedback", ["conversation_id"])
    op.create_index("ix_message_feedback_message_id", "message_feedback", ["message_id"])
    # A unique index is portable across PostgreSQL and SQLite batch migration
    # backends while providing the same idempotency guarantee.
    op.create_index(
        "uq_message_feedback_user_message",
        "message_feedback",
        ["user_id", "message_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_message_feedback_user_message", table_name="message_feedback")
    op.drop_index("ix_message_feedback_message_id", table_name="message_feedback")
    op.drop_index("ix_message_feedback_conversation_id", table_name="message_feedback")
    op.drop_index("ix_message_feedback_user_id", table_name="message_feedback")
    op.drop_table("message_feedback")
