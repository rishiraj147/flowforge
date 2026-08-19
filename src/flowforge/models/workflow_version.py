"""Immutable workflow version snapshots.

Each row is a frozen copy of a workflow's definition at a point in time.
Executions (Phase 2.5+) will reference a version id — never the mutable
workflows row — so a running job keeps the same DAG even if the user edits.

DESIGN NOTES:
- `definition` is INSERT-only in application code (no UPDATE on this column).
- `version_number` is 1-based and monotonic per workflow (1, 2, 3…).
- `created_by` records who published this version (optional audit trail).
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from flowforge.models.base import Base

if TYPE_CHECKING:
    from flowforge.models.workflow import Workflow


class WorkflowVersion(Base):
    __tablename__ = "workflow_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    version_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    definition: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default="{}",
        nullable=False,
    )

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    workflow: Mapped["Workflow"] = relationship(
        "Workflow",
        back_populates="versions",
        foreign_keys=[workflow_id],
    )

    __table_args__ = (
        UniqueConstraint(
            "workflow_id",
            "version_number",
            name="uq_workflow_versions_workflow_id_version_number",
        ),
        Index(
            "ix_workflow_versions_workflow_id_version_number",
            "workflow_id",
            "version_number",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"WorkflowVersion(id={self.id!r}, "
            f"workflow_id={self.workflow_id!r}, "
            f"version_number={self.version_number!r})"
        )
