"""Workflow artifact metadata — bytes live in S3; Postgres stores pointers."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from flowforge.models.base import Base


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # SHA-256 hex — same bytes share one S3 object (content-addressed)
    content_hash: Mapped[str] = mapped_column(
        String(64),
        index=True,
        nullable=False,
    )

    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)

    filename: Mapped[str] = mapped_column(String(512), nullable=False)

    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)

    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("executions.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    task_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("task_runs.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"Artifact(id={self.id!r}, content_hash={self.content_hash!r}, "
            f"filename={self.filename!r})"
        )
