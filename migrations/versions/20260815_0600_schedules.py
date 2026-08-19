"""schedules, schedule_fires, execution trigger metadata

Revision ID: f2a8c1d9045b
Revises: e1b7c3d9024a
Create Date: 2026-08-15 06:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2a8c1d9045b"
down_revision: Union[str, None] = "e1b7c3d9024a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "schedules",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workflow_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("cron_expression", sa.String(length=100), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_schedules_workflow_id"), "schedules", ["workflow_id"])

    op.add_column(
        "executions",
        sa.Column(
            "trigger_source",
            sa.String(length=20),
            server_default="manual",
            nullable=False,
        ),
    )
    op.add_column("executions", sa.Column("schedule_id", sa.UUID(), nullable=True))
    op.create_index(op.f("ix_executions_schedule_id"), "executions", ["schedule_id"])
    op.create_foreign_key(
        "fk_executions_schedule_id_schedules",
        "executions",
        "schedules",
        ["schedule_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "schedule_fires",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("schedule_id", sa.UUID(), nullable=False),
        sa.Column("fire_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("execution_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["execution_id"], ["executions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["schedule_id"], ["schedules.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "schedule_id",
            "fire_at",
            name="uq_schedule_fires_schedule_id_fire_at",
        ),
    )
    op.create_index(
        op.f("ix_schedule_fires_schedule_id"),
        "schedule_fires",
        ["schedule_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_schedule_fires_schedule_id"), table_name="schedule_fires")
    op.drop_table("schedule_fires")
    op.drop_constraint(
        "fk_executions_schedule_id_schedules",
        "executions",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_executions_schedule_id"), table_name="executions")
    op.drop_column("executions", "schedule_id")
    op.drop_column("executions", "trigger_source")
    op.drop_index(op.f("ix_schedules_workflow_id"), table_name="schedules")
    op.drop_table("schedules")
