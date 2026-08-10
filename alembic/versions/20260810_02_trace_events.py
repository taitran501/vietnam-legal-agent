"""add corpus-aware agent traces

Revision ID: 20260810_02
Revises: 20260810_01
Create Date: 2026-08-10
"""

from alembic import op
import sqlalchemy as sa


revision = "20260810_02"
down_revision = "20260810_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch:
        batch.add_column(sa.Column("corpus_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("pipeline_version", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("source", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("duration_ms", sa.Float(), nullable=True))
        batch.add_column(sa.Column("evidence_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("cache_status", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("error_code", sa.String(length=128), nullable=True))
    op.create_table(
        "agent_run_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trace_id", sa.String(length=128), sa.ForeignKey("agent_runs.trace_id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("node", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=128), nullable=False),
        sa.Column("tool_name", sa.String(length=64), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_run_events_trace_id", "agent_run_events", ["trace_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_run_events_trace_id", table_name="agent_run_events")
    op.drop_table("agent_run_events")
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_column("error_code")
        batch.drop_column("cache_status")
        batch.drop_column("evidence_count")
        batch.drop_column("duration_ms")
        batch.drop_column("source")
        batch.drop_column("pipeline_version")
        batch.drop_column("corpus_id")
