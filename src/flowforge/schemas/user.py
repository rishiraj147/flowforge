"""Pydantic schemas for the User feature.

WHY separate from src/flowforge/models/user.py (the ORM model):
- ORM model = how the row is stored in Postgres (includes password_hash).
- Pydantic schema = what crosses the HTTP boundary (NEVER includes password_hash).
Mixing them is the #1 source of "we leaked password hashes in our API response"
bugs. Keeping them apart is the standard production split.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    """Request body for POST /auth/register.

    EmailStr validates the format (a@b.c). Field(min_length=8) is a baseline
    password rule — real apps add complexity rules, breach-database checks, etc.
    """

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = None


class UserRead(BaseModel):
    """Response body. NOTE the fields we EXCLUDE: password, password_hash.

    from_attributes=True lets Pydantic build this from a SQLAlchemy ORM instance
    by reading attributes (user.id, user.email, ...). Without it, FastAPI would
    try to treat the ORM object as a dict and fail.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    created_at: datetime