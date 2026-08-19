"""Workflow business logic.

Pure functions over an AsyncSession. No FastAPI, no HTTP, no Pydantic models.
This file would work unchanged if FlowForge were a CLI or a background worker.

Versioning rules:
- `definition` lives on immutable WorkflowVersion rows.
- CREATE inserts workflow + v1, then sets current_version_id.
- PATCH that changes definition inserts v(N+1) and moves the pointer.
- Identical definition payloads skip a new version (no-op content update).
- Metadata fields (name, description, status) update the workflows row directly.

The CURSOR pagination scheme:
    cursor = base64(json({"c": "<iso_created_at>", "i": "<uuid>"}))

Encoded so it's safe in URLs and opaque to clients (they shouldn't parse it;
they should pass it back verbatim).
"""

import base64
import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from flowforge.dag import validate_dag
from flowforge.models import Workflow, WorkflowVersion

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# Column attrs to refresh after commit. We intentionally skip relationships —
# `current_version` is kept in memory (avoids stale FK + MissingGreenlet on lazy load).
_WORKFLOW_COLUMN_ATTRS = [
    "name",
    "description",
    "current_version_id",
    "status",
    "owner_id",
    "created_at",
    "updated_at",
]


# ---------- cursor codec ----------

def _encode_cursor(created_at: datetime, row_id: uuid.UUID) -> str:
    payload = {"c": created_at.isoformat(), "i": str(row_id)}
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """Reverse of _encode_cursor. Raises ValueError if the cursor is malformed.

    The "+" "===" handles missing padding (urlsafe_b64encode + rstrip("=") above).
    """

    padded = cursor + "=" * (-len(cursor) % 4)
    raw = base64.urlsafe_b64decode(padded.encode("utf-8"))
    payload = json.loads(raw)

    return (
        datetime.fromisoformat(payload["c"]),
        uuid.UUID(payload["i"]),
    )


def _workflow_load_options() -> tuple[Any, ...]:
    """Eager-load current_version so WorkflowRead properties resolve."""
    return (selectinload(Workflow.current_version),)


# ---------- CRUD ----------

async def create(
    session: AsyncSession,
    *,
    owner_id: uuid.UUID,
    name: str,
    description: str | None,
    definition: dict[str, Any],
) -> Workflow:
    validate_dag(definition)

    wf = Workflow(
        owner_id=owner_id,
        name=name,
        description=description,
    )
    session.add(wf)
    await session.flush()

    version = WorkflowVersion(
        workflow_id=wf.id,
        version_number=1,
        definition=definition,
        created_by=owner_id,
    )
    session.add(version)
    await session.flush()

    wf.current_version_id = version.id
    wf.current_version = version

    await session.commit()

    result = await session.execute(
        select(Workflow)
        .where(Workflow.id == wf.id)
        .options(*_workflow_load_options())
    )

    return result.scalar_one()


async def get(
    session: AsyncSession,
    workflow_id: uuid.UUID,
) -> Workflow | None:
    result = await session.execute(
        select(Workflow)
        .where(Workflow.id == workflow_id)
        .options(*_workflow_load_options())
    )

    return result.scalar_one_or_none()


async def update(
    session: AsyncSession,
    workflow_id: uuid.UUID,
    patch: dict[str, Any],
    *,
    updated_by_id: uuid.UUID,
) -> Workflow | None:
    """Apply a partial update. `patch` should already be {only fields the client sent}.

    Definition changes create a new immutable version; other fields update metadata.
    """

    result = await session.execute(
        select(Workflow)
        .where(Workflow.id == workflow_id)
        .options(*_workflow_load_options())
    )
    wf = result.scalar_one_or_none()

    if wf is None:
        return None

    new_definition = patch.pop("definition", None)
    bumped_version: WorkflowVersion | None = None

    if new_definition is not None:
        validate_dag(new_definition)

        current = wf.current_version
        current_definition = current.definition if current is not None else {}

        if new_definition != current_definition:
            next_number = (current.version_number if current is not None else 0) + 1

            version = WorkflowVersion(
                workflow_id=wf.id,
                version_number=next_number,
                definition=new_definition,
                created_by=updated_by_id,
            )
            session.add(version)
            await session.flush()

            bumped_version = version
            wf.current_version_id = version.id
            wf.current_version = version

    for field, value in patch.items():
        setattr(wf, field, value)

    await session.commit()
    # Server-side onupdate=func.now() expires updated_at on flush; async refresh
    # reloads columns without lazy-load (MissingGreenlet in FastAPI response path).
    await session.refresh(wf, attribute_names=_WORKFLOW_COLUMN_ATTRS)

    if bumped_version is not None:
        # expire_on_commit=False keeps stale relationship objects in memory — re-wire.
        wf.current_version = bumped_version

    return wf


async def delete_one(
    session: AsyncSession,
    workflow_id: uuid.UUID,
) -> bool:
    """Returns True if a row was deleted, False if no such workflow."""

    result = await session.execute(
        delete(Workflow).where(Workflow.id == workflow_id)
    )

    await session.commit()

    return result.rowcount > 0


# ---------- version history ----------

async def list_versions(
    session: AsyncSession,
    workflow_id: uuid.UUID,
) -> list[WorkflowVersion] | None:
    """Return all versions for a workflow, newest first. None if workflow missing."""

    wf = await session.get(Workflow, workflow_id)

    if wf is None:
        return None

    result = await session.execute(
        select(WorkflowVersion)
        .where(WorkflowVersion.workflow_id == workflow_id)
        .order_by(WorkflowVersion.version_number.desc())
    )

    return list(result.scalars().all())


async def get_version(
    session: AsyncSession,
    workflow_id: uuid.UUID,
    version_number: int,
) -> WorkflowVersion | None:
    """Fetch one immutable snapshot by workflow id + version number."""

    result = await session.execute(
        select(WorkflowVersion).where(
            WorkflowVersion.workflow_id == workflow_id,
            WorkflowVersion.version_number == version_number,
        )
    )

    return result.scalar_one_or_none()


# ---------- listing with cursor pagination ----------

async def list_page(
    session: AsyncSession,
    *,
    cursor: str | None,
    limit: int,
) -> tuple[list[Workflow], str | None]:
    """Return (items, next_cursor).

    Sort: (created_at DESC, id DESC). Newest first; id breaks ties when two
    rows share a microsecond (rare but real).

    Trick: we fetch limit+1 rows. If we got exactly limit+1, there IS a next
    page, and we use the (limit+1)th row's position as the next cursor. We
    only RETURN the first `limit` rows to the client.
    """

    limit = max(1, min(limit, MAX_PAGE_SIZE))

    stmt = (
        select(Workflow)
        .options(*_workflow_load_options())
        .order_by(
            Workflow.created_at.desc(),
            Workflow.id.desc(),
        )
    )

    if cursor is not None:
        try:
            ts, row_id = _decode_cursor(cursor)

        except (ValueError, KeyError, json.JSONDecodeError):
            ts, row_id = None, None

        if ts is not None:
            stmt = stmt.where(
                or_(
                    Workflow.created_at < ts,
                    and_(
                        Workflow.created_at == ts,
                        Workflow.id < row_id,
                    ),
                )
            )

    stmt = stmt.limit(limit + 1)

    rows = list(
        (await session.execute(stmt))
        .scalars()
        .all()
    )

    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = _encode_cursor(last.created_at, last.id)
        rows = rows[:limit]
    else:
        next_cursor = None

    return rows, next_cursor
