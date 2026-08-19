"""unique task_run per execution+step

Revision ID: e1b7c3d9024a
Revises: d9e2a4f8c601
Create Date: 2026-08-14 18:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "e1b7c3d9024a"
down_revision: Union[str, None] = "d9e2a4f8c601"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_task_runs_execution_id_step_id",
        "task_runs",
        ["execution_id", "step_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_task_runs_execution_id_step_id",
        "task_runs",
        type_="unique",
    )
