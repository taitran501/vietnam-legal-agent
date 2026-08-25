"""add trace-linked quality feedback triage"""

import sqlalchemy as sa
from alembic import op

revision = "20260825_07"
down_revision = "20260813_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quality_feedback",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("feedback_id", sa.Integer(), sa.ForeignKey("message_feedback.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(length=128), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "conversation_id",
            sa.String(length=128),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trace_id", sa.String(length=128), nullable=True),
        sa.Column("failure_category", sa.String(length=64), nullable=False, server_default="unclassified"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="new"),
        sa.Column("evidence_snapshot", sa.JSON(), nullable=False),
        sa.Column("reviewer_id", sa.String(length=128), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("dataset_case_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_quality_feedback_feedback_id", "quality_feedback", ["feedback_id"], unique=True)
    op.create_index("ix_quality_feedback_user_id", "quality_feedback", ["user_id"])
    op.create_index("ix_quality_feedback_conversation_id", "quality_feedback", ["conversation_id"])
    op.create_index("ix_quality_feedback_message_id", "quality_feedback", ["message_id"])
    op.create_index("ix_quality_feedback_trace_id", "quality_feedback", ["trace_id"])
    op.create_index("ix_quality_feedback_status", "quality_feedback", ["status"])
    op.create_index("ix_quality_feedback_failure_category", "quality_feedback", ["failure_category"])


def downgrade() -> None:
    op.drop_index("ix_quality_feedback_failure_category", table_name="quality_feedback")
    op.drop_index("ix_quality_feedback_status", table_name="quality_feedback")
    op.drop_index("ix_quality_feedback_trace_id", table_name="quality_feedback")
    op.drop_index("ix_quality_feedback_message_id", table_name="quality_feedback")
    op.drop_index("ix_quality_feedback_conversation_id", table_name="quality_feedback")
    op.drop_index("ix_quality_feedback_user_id", table_name="quality_feedback")
    op.drop_index("ix_quality_feedback_feedback_id", table_name="quality_feedback")
    op.drop_table("quality_feedback")

