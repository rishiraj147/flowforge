"""webhooks, webhook_deliveries, execution webhook_id

Revision ID: a3b9d2e1056c
Revises: f2a8c1d9045b
Create Date: 2026-08-15 07:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3b9d2e1056c"
down_revision: Union[str, None] = "f2a8c1d9045b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "webhooks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workflow_id", sa.UUID(), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("secret", sa.String(length=128), nullable=False),
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
        sa.UniqueConstraint("workflow_id"),
        sa.UniqueConstraint("token"),
    )
    op.create_index(op.f("ix_webhooks_workflow_id"), "webhooks", ["workflow_id"])
    op.create_index(op.f("ix_webhooks_token"), "webhooks", ["token"])

    op.add_column("executions", sa.Column("webhook_id", sa.UUID(), nullable=True))
    op.create_index(op.f("ix_executions_webhook_id"), "executions", ["webhook_id"])
    op.create_foreign_key(
        "fk_executions_webhook_id_webhooks",
        "executions",
        "webhooks",
        ["webhook_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("webhook_id", sa.UUID(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("execution_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["execution_id"], ["executions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["webhook_id"], ["webhooks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "webhook_id",
            "idempotency_key",
            name="uq_webhook_deliveries_webhook_idempotency",
        ),
    )
    op.create_index(
        op.f("ix_webhook_deliveries_webhook_id"),
        "webhook_deliveries",
        ["webhook_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_webhook_deliveries_webhook_id"), table_name="webhook_deliveries")
    op.drop_table("webhook_deliveries")
    op.drop_constraint(
        "fk_executions_webhook_id_webhooks",
        "executions",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_executions_webhook_id"), table_name="executions")
    op.drop_column("executions", "webhook_id")
    op.drop_index(op.f("ix_webhooks_token"), table_name="webhooks")
    op.drop_index(op.f("ix_webhooks_workflow_id"), table_name="webhooks")
    op.drop_table("webhooks")
