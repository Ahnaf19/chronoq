"""Initial telemetry table creation.

Revision ID: 001
Revises: None
Create Date: 2026-03-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "telemetry",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_type", sa.Text(), nullable=False),
        sa.Column("payload_size", sa.Integer()),
        sa.Column("actual_ms", sa.Float(), nullable=False),
        sa.Column("metadata_json", sa.Text()),
        sa.Column("recorded_at", sa.Text(), nullable=False),
        sa.Column("model_version_at_record", sa.Text()),
    )


def downgrade() -> None:
    op.drop_table("telemetry")
