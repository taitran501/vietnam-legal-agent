"""add pipeline V3 identity fields to agent runs

Revision ID: 20260810_03
Revises: 20260810_02
Create Date: 2026-08-10
"""

import sqlalchemy as sa
from alembic import op

revision = "20260810_03"
down_revision = "20260810_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch:
        batch.add_column(sa.Column("route", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("corpus_sha", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("embedding_profile", sa.String(length=128), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_column("embedding_profile")
        batch.drop_column("corpus_sha")
        batch.drop_column("route")
