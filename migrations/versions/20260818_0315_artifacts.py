"""artifacts table for S3 object metadata

Revision ID: b4c8e3f2067d
Revises: a3b9d2e1056c
Create Date: 2026-08-18 03:15:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b4c8e3f2067d"
down_revision: Union[str, None] = "a3b9d2e1056c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "artifacts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("execution_id", sa.UUID(), nullable=True),
        sa.Column("task_run_id", sa.UUID(), nullable=True),
        sa.Column("uploaded_by", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["execution_id"], ["executions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_run_id"], ["task_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_artifacts_content_hash"), "artifacts", ["content_hash"])
    op.create_index(op.f("ix_artifacts_execution_id"), "artifacts", ["execution_id"])
    op.create_index(op.f("ix_artifacts_task_run_id"), "artifacts", ["task_run_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_artifacts_task_run_id"), table_name="artifacts")
    op.drop_index(op.f("ix_artifacts_execution_id"), table_name="artifacts")
    op.drop_index(op.f("ix_artifacts_content_hash"), table_name="artifacts")
    op.drop_table("artifacts")
