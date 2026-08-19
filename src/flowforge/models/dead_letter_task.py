"""Dead-letter record — Celery task that exhausted automatic retries."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from flowforge.models.base import Base


class DeadLetterTask(Base):
    """DLQ row — durable audit of permanently failed step runs.

    Celery has no built-in DLQ like SQS; Postgres + replay API is the pattern.
    """

    __tablename__ = "dead_letter_tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    task_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("task_runs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    task_name: Mapped[str] = mapped_column(String(255), nullable=False)

    error: Mapped[str] = mapped_column(Text, nullable=False)

    traceback: Mapped[str | None] = mapped_column(Text, nullable=True)

    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # pending | replayed
    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        server_default="pending",
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    replayed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"DeadLetterTask(id={self.id!r}, task_run_id={self.task_run_id!r}, "
            f"status={self.status!r})"
        )
