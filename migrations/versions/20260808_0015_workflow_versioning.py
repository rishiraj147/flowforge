"""workflow versioning — immutable workflow_versions table

Revision ID: c4a8f2e1b903
Revises: b3269289c7b3
Create Date: 2026-08-08 00:15:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c4a8f2e1b903"
down_revision: Union[str, None] = "b3269289c7b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
  # 1. Create immutable version snapshots (workflow_id FK only — no circular FK yet).
  op.create_table(
    "workflow_versions",
    sa.Column("id", sa.UUID(), nullable=False),
    sa.Column("workflow_id", sa.UUID(), nullable=False),
    sa.Column("version_number", sa.Integer(), nullable=False),
    sa.Column(
      "definition",
      postgresql.JSONB(astext_type=sa.Text()),
      server_default="{}",
      nullable=False,
    ),
    sa.Column("created_by", sa.UUID(), nullable=True),
    sa.Column(
      "created_at",
      sa.DateTime(timezone=True),
      server_default=sa.text("now()"),
      nullable=False,
    ),
    sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
    sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="CASCADE"),
    sa.PrimaryKeyConstraint("id"),
    sa.UniqueConstraint(
      "workflow_id",
      "version_number",
      name="uq_workflow_versions_workflow_id_version_number",
    ),
  )
  op.create_index(
    op.f("ix_workflow_versions_workflow_id"),
    "workflow_versions",
    ["workflow_id"],
    unique=False,
  )
  op.create_index(
    "ix_workflow_versions_workflow_id_version_number",
    "workflow_versions",
    ["workflow_id", "version_number"],
    unique=False,
  )

  # 2. Backfill v1 from existing workflows.definition rows.
  op.execute(
    sa.text(
      """
      INSERT INTO workflow_versions (
        id, workflow_id, version_number, definition, created_by, created_at
      )
      SELECT
        gen_random_uuid(),
        w.id,
        1,
        w.definition,
        w.owner_id,
        w.created_at
      FROM workflows w
      """
    )
  )

  # 3. Pointer column on workflows (nullable during backfill).
  op.add_column(
    "workflows",
    sa.Column("current_version_id", sa.UUID(), nullable=True),
  )
  op.create_index(
    op.f("ix_workflows_current_version_id"),
    "workflows",
    ["current_version_id"],
    unique=False,
  )

  # 4. Point each workflow at its v1 row.
  op.execute(
    sa.text(
      """
      UPDATE workflows w
      SET current_version_id = v.id
      FROM workflow_versions v
      WHERE v.workflow_id = w.id AND v.version_number = 1
      """
    )
  )

  # 5. FK from workflows -> workflow_versions (circular, but Postgres allows it).
  op.create_foreign_key(
    "fk_workflows_current_version_id",
    "workflows",
    "workflow_versions",
    ["current_version_id"],
    ["id"],
    ondelete="RESTRICT",
  )

  # 6. Drop inline definition — content now lives only on version rows.
  op.drop_column("workflows", "definition")


def downgrade() -> None:
  op.add_column(
    "workflows",
    sa.Column(
      "definition",
      postgresql.JSONB(astext_type=sa.Text()),
      server_default="{}",
      nullable=False,
    ),
  )

  op.execute(
    sa.text(
      """
      UPDATE workflows w
      SET definition = v.definition
      FROM workflow_versions v
      WHERE v.id = w.current_version_id
      """
    )
  )

  op.drop_constraint(
    "fk_workflows_current_version_id",
    "workflows",
    type_="foreignkey",
  )
  op.drop_index(op.f("ix_workflows_current_version_id"), table_name="workflows")
  op.drop_column("workflows", "current_version_id")

  op.drop_index(
    "ix_workflow_versions_workflow_id_version_number",
    table_name="workflow_versions",
  )
  op.drop_index(
    op.f("ix_workflow_versions_workflow_id"),
    table_name="workflow_versions",
  )
  op.drop_table("workflow_versions")
