"""Pydantic schemas for the Workflow feature.

We define FOUR schemas:

- WorkflowCreate  — what the client SENDS on POST. No id/owner/timestamps (server-set).
- WorkflowUpdate  — what the client SENDS on PATCH. ALL fields optional.
- WorkflowRead    — what the server RETURNS. Includes server-set fields.
- WorkflowPage    — the paginated list response: items + next_cursor.

Why so many? Each direction has DIFFERENT field sets and DIFFERENT validation
rules. Sharing one schema would either expose internal fields to clients or
demand server-set fields from clients. Both are bugs.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# ---------- inputs ----------

class WorkflowCreate(BaseModel):
    """POST /workflows body.

    Notice what's NOT here: id (server generates), owner_id (server = current user),
    created_at, updated_at, status (defaults to "draft"). A client cannot set ANY
    of those via this endpoint — Pydantic ignores unknown fields silently.
    """

    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)
    definition: dict[str, Any] = Field(default_factory=dict)


class WorkflowUpdate(BaseModel):
    """PATCH /workflows/{id} body. EVERY field optional.

    The handler uses `body.model_dump(exclude_unset=True)` to get only the
    fields the client explicitly sent — fields the client omitted are NOT
    treated as "set to null." That's the PATCH contract.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)
    definition: dict[str, Any] | None = None
    status: Literal["draft", "active", "archived"] | None = None


# ---------- outputs ----------

class WorkflowRead(BaseModel):
    """Single workflow response.

    from_attributes=True lets Pydantic build this directly from an ORM Workflow
    instance by reading attributes — no manual dict conversion.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    definition: dict[str, Any]
    status: str
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class WorkflowPage(BaseModel):
    """Paginated list response.

    `next_cursor` is the opaque token to pass back to fetch the next page.
    When None, the client knows it has reached the end.

    Why a wrapper object instead of just a JSON array? Because we need somewhere
    to put `next_cursor`. Returning bare arrays is fine for tiny endpoints, but
    paginated endpoints always need this wrapper shape.
    """

    items: list[WorkflowRead]
    next_cursor: str | None