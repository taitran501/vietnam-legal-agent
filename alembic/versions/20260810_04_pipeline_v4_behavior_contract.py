"""add Pipeline V4 case and run contracts

Revision ID: 20260810_04
Revises: 20260810_03
Create Date: 2026-08-10
"""

import sqlalchemy as sa
from alembic import op

revision = "20260810_04"
down_revision = "20260810_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("case_states") as batch:
        batch.add_column(sa.Column("schema_version", sa.String(length=32), nullable=False, server_default="legacy-v3"))
        batch.add_column(sa.Column("decision_status", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("issue_states", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
        batch.add_column(sa.Column("as_of_date", sa.String(length=32), nullable=False, server_default=""))
    with op.batch_alter_table("agent_runs") as batch:
        batch.add_column(sa.Column("outcome", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("result_type", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("understanding_confidence", sa.Float(), nullable=True))
        batch.add_column(sa.Column("required_issue_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("covered_issue_count", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_column("covered_issue_count")
        batch.drop_column("required_issue_count")
        batch.drop_column("understanding_confidence")
        batch.drop_column("result_type")
        batch.drop_column("outcome")
    with op.batch_alter_table("case_states") as batch:
        batch.drop_column("as_of_date")
        batch.drop_column("issue_states")
        batch.drop_column("decision_status")
        batch.drop_column("schema_version")
