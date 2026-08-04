"""Workflow business logic.

Pure functions over an AsyncSession. No FastAPI, no HTTP, no Pydantic models.
This file would work unchanged if FlowForge were a CLI or a background worker.

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

from flowforge.dag import validate_dag
from flowforge.models import Workflow

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


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


# ---------- CRUD ----------

async def create(
    session: AsyncSession,
    *,
    owner_id: uuid.UUID,
    name: str,
    description: str | None,
    definition: dict[str, Any],
) -> Workflow:
    # Validate BEFORE we touch the DB. If the DAG is bad, we never write a row.
    # Raises DAGValidationError -> router translates to 422.
    validate_dag(definition)

    wf = Workflow(
        owner_id=owner_id,
        name=name,
        description=description,
        definition=definition,
    )

    session.add(wf)
    await session.commit()
    await session.refresh(wf)  # reload server-side defaults (id, created_at, status)

    return wf


async def get(
    session: AsyncSession,
    workflow_id: uuid.UUID,
) -> Workflow | None:
    return await session.get(Workflow, workflow_id)


async def update(
    session: AsyncSession,
    workflow_id: uuid.UUID,
    patch: dict[str, Any],
) -> Workflow | None:
    """Apply a partial update. `patch` should already be {only fields the client sent}.

    If patch is empty (client sent {} body), this is a no-op except for the
    `updated_at` bump — fine, idempotent.
    """

    wf = await session.get(Workflow, workflow_id)
    if wf is None:
        return None

    # If the caller is changing the definition, re-validate the new DAG
    # BEFORE persisting. Otherwise an edit could turn a valid workflow into an cycle one.
    if "definition" in patch:
        validate_dag(patch["definition"])

    for field, value in patch.items():
        setattr(wf, field, value)

    await session.commit()
    await session.refresh(wf)

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

    stmt = select(Workflow).order_by(
        Workflow.created_at.desc(),
        Workflow.id.desc(),
    )

    if cursor is not None:
        try:
            ts, row_id = _decode_cursor(cursor)

        except (ValueError, KeyError, json.JSONDecodeError):
            # Malformed cursor — treat as "start from beginning". Alternative:
            # raise 400. Either is defensible; "ignore garbage" is friendlier.
            ts, row_id = None, None

        if ts is not None:
            # (created_at, id) < (ts, row_id)
            # expressed across OR because SQLAlchemy doesn't compile tuple
            # comparisons across all dialects.
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