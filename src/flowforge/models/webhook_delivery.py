"""Webhook delivery log — idempotency per (webhook, idempotency_key)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from flowforge.models.base import Base


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    webhook_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("webhooks.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)

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
            "webhook_id",
            "idempotency_key",
            name="uq_webhook_deliveries_webhook_idempotency",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"WebhookDelivery(webhook_id={self.webhook_id!r}, "
            f"idempotency_key={self.idempotency_key!r})"
        )
