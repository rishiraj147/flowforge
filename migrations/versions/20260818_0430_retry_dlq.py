"""dead_letter_tasks + task_runs.retry_count

Revision ID: c5d9f4a3178e
Revises: b4c8e3f2067d
Create Date: 2026-08-18 04:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c5d9f4a3178e"
down_revision: Union[str, None] = "b4c8e3f2067d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "task_runs",
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
    )

    op.create_table(
        "dead_letter_tasks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("task_run_id", sa.UUID(), nullable=False),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column("task_name", sa.String(length=255), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("traceback", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("replayed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["task_run_id"], ["task_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_dead_letter_tasks_task_run_id"),
        "dead_letter_tasks",
        ["task_run_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_dead_letter_tasks_task_run_id"), table_name="dead_letter_tasks")
    op.drop_table("dead_letter_tasks")
    op.drop_column("task_runs", "retry_count")
