"""Idempotent cron fire log — one row per schedule occurrence."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from flowforge.models.base import Base


class ScheduleFire(Base):
    """Records a single cron slot fire so duplicate triggers are skipped."""

    __tablename__ = "schedule_fires"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    schedule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schedules.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    fire_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("executions.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "schedule_id",
            "fire_at",
            name="uq_schedule_fires_schedule_id_fire_at",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"ScheduleFire(schedule_id={self.schedule_id!r}, fire_at={self.fire_at!r})"
        )
