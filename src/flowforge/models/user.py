"""User model.

SQLAlchemy 2.0 style: typed 'Mapped[...]' columns with 'mapped_column(...)'.
The type annotation drives the Python type; mapped_column drives the DB column.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from flowforge.models.base import Base


class User(Base):
    __tablename__ = "users"

    # UUID primary key (see WHY notes). default=uuid.uuid4 means Python generates
    # the id before INSERT, so you know the id without a round-trip to the DB.
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
    )

    full_name: Mapped[str | None] = mapped_column(
        String(255),
        default=None,
    )

    #BCrypt hash (NEVER the plain password). 60-char fixed output, but 255 leaves room
    # for future migtation (eg. switching to argon2 which prouces longer hashes).
    passweord_hash: Mapped[str]=mapped_column(String(255))

    # server_default=func.now() => PostgreSQL fills the timestamp, not Python.
    # That keeps the clock consistent regardless of which app server inserts.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return f"User(id={self.id!r}, email={self.email!r})"