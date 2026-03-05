"""Add indexes for common query patterns.

Revision ID: 002
Revises: 001
Create Date: 2026-03-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_telemetry_task_type", "telemetry", ["task_type"])
    op.create_index("ix_telemetry_model_version", "telemetry", ["model_version_at_record"])


def downgrade() -> None:
    op.drop_index("ix_telemetry_model_version", table_name="telemetry")
    op.drop_index("ix_telemetry_task_type", table_name="telemetry")
