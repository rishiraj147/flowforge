"""Workflow ORM model.

DESIGN NOTES:
- `definition` is JSONB (Postgres-native binary JSON). Lets us store an arbitrary
  workflow spec without designing a sub-table per step type. Trade: schema-less
  inside that column — validation is the application's job.
- `status` is a plain String column with a small enumerated value space. We do
  the validation in the Pydantic schema (Literal[...]) — defense in depth, but
  the DB is intentionally tolerant.
- `owner_id` is a FOREIGN KEY to users.id. Indexed because the most common query
  shape is "list MY workflows" (when we add ABAC).
- `(created_at, id)` is the natural sort key for cursor pagination. We index it
  to make that query O(log N + page_size).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from flowforge.models.base import Base


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

    # JSONB = binary JSON, indexable, queryable. Default-empty so a workflow can
    # be created in "draft" with no steps yet.
    definition: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default="{}",
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

    # Composite index supporting cursor pagination ORDER BY (created_at, id) DESC.
    # Postgres can scan this index in reverse for the latest-first query.
    __table_args__ = (
        Index("ix_workflows_created_at_id", "created_at", "id"),
    )

    def __repr__(self) -> str:
        return (
            f"Workflow(id={self.id!r}, "
            f"name={self.name!r}, "
            f"status={self.status!r})"
        )