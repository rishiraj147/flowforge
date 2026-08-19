"""Dead-letter queue management + retry backoff preview."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from flowforge.authz import Permission, require_permission
from flowforge.config import Settings, settings_from_request
from flowforge.db import get_session
from flowforge.models import User
from flowforge.retry_policy import describe_backoff
from flowforge.schemas.dead_letter import BackoffPreviewRead, DeadLetterTaskRead
from flowforge.schemas.execution import TaskRunRead
from flowforge.services import dead_letter_service

router = APIRouter(tags=["retry-policy"])


@router.get("/retry-policy/backoff", response_model=BackoffPreviewRead)
async def preview_retry_backoff(
    attempt: int = Query(0, ge=0, le=20),
    _r: User = Depends(require_permission(Permission.EXECUTIONS_READ)),
    settings: Settings = Depends(settings_from_request),
) -> BackoffPreviewRead:
    """Show exponential backoff math for one retry attempt."""

    row = describe_backoff(
        attempt,
        base_seconds=settings.retry_backoff_base_seconds,
        max_seconds=settings.retry_backoff_max_seconds,
    )

    return BackoffPreviewRead(
        attempt=row.attempt,
        base_seconds=row.base_seconds,
        max_seconds=row.max_seconds,
        delay_without_jitter=row.delay_without_jitter,
        delay_with_jitter=row.delay_with_jitter,
        formula=row.formula,
        celery_equivalent=(
            f"retry_backoff={settings.retry_backoff_base_seconds}, "
            f"retry_backoff_max={settings.retry_backoff_max_seconds}, "
            "retry_jitter=True"
        ),
    )


@router.get("/dead-letter", response_model=list[DeadLetterTaskRead])
async def list_dead_letter_tasks(
    status: str | None = Query(None, pattern="^(pending|replayed)$"),
    limit: int = Query(50, ge=1, le=200),
    _r: User = Depends(require_permission(Permission.DEAD_LETTER_READ)),
    session: AsyncSession = Depends(get_session),
) -> list[DeadLetterTaskRead]:
    entries = await dead_letter_service.list_dead_letter_tasks(
        session,
        status=status,
        limit=limit,
    )

    return [DeadLetterTaskRead.model_validate(e) for e in entries]


@router.get("/dead-letter/{entry_id}", response_model=DeadLetterTaskRead)
async def get_dead_letter_task(
    entry_id: uuid.UUID,
    _r: User = Depends(require_permission(Permission.DEAD_LETTER_READ)),
    session: AsyncSession = Depends(get_session),
) -> DeadLetterTaskRead:
    entry = await dead_letter_service.get_dead_letter_task(session, entry_id)

    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dead-letter entry not found")

    return DeadLetterTaskRead.model_validate(entry)


@router.post(
    "/dead-letter/{entry_id}/replay",
    response_model=TaskRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def replay_dead_letter_task(
    entry_id: uuid.UUID,
    _r: User = Depends(require_permission(Permission.DEAD_LETTER_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> TaskRunRead:
    """Manually re-queue a permanently failed step from the DLQ."""

    task_run = await dead_letter_service.replay_dead_letter(session, entry_id)

    if task_run is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Dead-letter entry not found or already replayed",
        )

    return TaskRunRead.model_validate(task_run)
