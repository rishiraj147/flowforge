"""Workflow ORM model — logical identity + metadata (not the DAG body).

The executable DAG lives on immutable WorkflowVersion rows. This table holds
stable identity (id, owner, status) and a pointer to the latest version.

DESIGN NOTES:
- `current_version_id` is nullable in the DB so we can INSERT the workflow row
  before its first version exists (flush ordering). Application code always sets
  it before commit.
- `definition` and `version_number` are exposed as read-only properties that
  delegate to `current_version` so API schemas can keep a flat WorkflowRead shape.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from flowforge.models.base import Base

if TYPE_CHECKING:
    from flowforge.models.workflow_version import WorkflowVersion


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    name: Mapped[str] = mapped_column(
        String(255),
        index=True,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        default=None,
    )

    # Pointer to the latest immutable snapshot. Executions pin a specific version id.
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_versions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    # draft -> active -> archived (validated in the Pydantic schema layer).
    status: Mapped[str] = mapped_column(
        String(20),
        default="draft",
        server_default="draft",
        nullable=False,
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        index=True,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # onupdate runs server-side on every UPDATE — even if nobody set this field.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    current_version: Mapped["WorkflowVersion | None"] = relationship(
        "WorkflowVersion",
        foreign_keys=[current_version_id],
        lazy="selectin",
    )

    versions: Mapped[list["WorkflowVersion"]] = relationship(
        "WorkflowVersion",
        back_populates="workflow",
        foreign_keys="WorkflowVersion.workflow_id",
        lazy="raise",
    )

    # Composite index supporting cursor pagination ORDER BY (created_at, id) DESC.
    __table_args__ = (
        Index("ix_workflows_created_at_id", "created_at", "id"),
    )

    @property
    def definition(self) -> dict[str, Any]:
        """DAG body from the current version (empty dict if not loaded yet)."""
        if self.current_version is None:
            return {}
        return self.current_version.definition

    @property
    def version_number(self) -> int:
        """Monotonic version counter from the current version row."""
        if self.current_version is None:
            return 0
        return self.current_version.version_number

    def __repr__(self) -> str:
        return (
            f"Workflow(id={self.id!r}, "
            f"name={self.name!r}, "
            f"status={self.status!r})"
        )
