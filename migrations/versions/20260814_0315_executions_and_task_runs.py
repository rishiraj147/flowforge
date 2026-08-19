"""executions and task_runs tables

Revision ID: d9e2a4f8c601
Revises: c4a8f2e1b903
Create Date: 2026-08-14 03:15:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d9e2a4f8c601"
down_revision: Union[str, None] = "c4a8f2e1b903"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "executions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workflow_id", sa.UUID(), nullable=False),
        sa.Column("workflow_version_id", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("triggered_by", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["triggered_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workflow_version_id"],
            ["workflow_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_executions_workflow_id"), "executions", ["workflow_id"])
    op.create_index(
        op.f("ix_executions_workflow_version_id"),
        "executions",
        ["workflow_version_id"],
    )

    op.create_table(
        "task_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("execution_id", sa.UUID(), nullable=False),
        sa.Column("step_id", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["execution_id"], ["executions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_task_runs_execution_id"), "task_runs", ["execution_id"])
    op.create_index(
        op.f("ix_task_runs_celery_task_id"),
        "task_runs",
        ["celery_task_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_task_runs_celery_task_id"), table_name="task_runs")
    op.drop_index(op.f("ix_task_runs_execution_id"), table_name="task_runs")
    op.drop_table("task_runs")
    op.drop_index(op.f("ix_executions_workflow_version_id"), table_name="executions")
    op.drop_index(op.f("ix_executions_workflow_id"), table_name="executions")
    op.drop_table("executions")
