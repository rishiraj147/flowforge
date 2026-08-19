"""Cron schedule REST endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from flowforge.authz import Permission, require_permission
from flowforge.cron_parser import CronExpressionError, decode_cron_expression as parse_cron_expression
from flowforge.db import get_session
from flowforge.models import User
from flowforge.scheduler import WorkflowCronScheduler
from flowforge.schemas.schedule import (
    CronDecodeRead,
    ScheduleCreate,
    ScheduleRead,
    ScheduleTriggerResult,
    ScheduleUpdate,
)
from flowforge.services import schedule_service

router = APIRouter(tags=["schedules"])


def _cron_error_to_http(exc: CronExpressionError) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"message": str(exc)},
    )


def _get_scheduler(request: Request) -> WorkflowCronScheduler | None:
    return getattr(request.app.state, "scheduler", None)


@router.get(
    "/schedules/cron/decode",
    response_model=CronDecodeRead,
)
async def explain_cron_expression(
    expression: str = Query(min_length=1, max_length=100),
    _r: User = Depends(require_permission(Permission.SCHEDULES_READ)),
) -> CronDecodeRead:
    """Explain a cron expression (teaching endpoint)."""

    try:
        decoded = parse_cron_expression(expression)
    except CronExpressionError as exc:
        raise _cron_error_to_http(exc) from exc

    return CronDecodeRead(**decoded)


@router.post(
    "/workflows/{workflow_id}/schedules",
    response_model=ScheduleRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_workflow_schedule(
    workflow_id: uuid.UUID,
    body: ScheduleCreate,
    request: Request,
    current_user: User = Depends(require_permission(Permission.SCHEDULES_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> ScheduleRead:
    try:
        schedule = await schedule_service.create_schedule(
            session,
            workflow_id=workflow_id,
            owner_id=current_user.id,
            name=body.name,
            cron_expression=body.cron_expression,
            enabled=body.enabled,
        )
    except CronExpressionError as exc:
        raise _cron_error_to_http(exc) from exc

    if schedule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found")

    scheduler = _get_scheduler(request)

    if scheduler is not None:
        await scheduler.sync_schedule(schedule)

    return schedule  # type: ignore[return-value]


@router.get(
    "/workflows/{workflow_id}/schedules",
    response_model=list[ScheduleRead],
)
async def list_workflow_schedules(
    workflow_id: uuid.UUID,
    _r: User = Depends(require_permission(Permission.SCHEDULES_READ)),
    session: AsyncSession = Depends(get_session),
) -> list[ScheduleRead]:
    schedules = await schedule_service.list_schedules_for_workflow(session, workflow_id)

    if schedules is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found")

    return schedules  # type: ignore[return-value]


@router.get(
    "/schedules/{schedule_id}",
    response_model=ScheduleRead,
)
async def get_schedule(
    schedule_id: uuid.UUID,
    _r: User = Depends(require_permission(Permission.SCHEDULES_READ)),
    session: AsyncSession = Depends(get_session),
) -> ScheduleRead:
    schedule = await schedule_service.get_schedule(session, schedule_id)

    if schedule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found")

    return schedule  # type: ignore[return-value]


@router.patch(
    "/schedules/{schedule_id}",
    response_model=ScheduleRead,
)
async def update_schedule(
    schedule_id: uuid.UUID,
    body: ScheduleUpdate,
    request: Request,
    _w: User = Depends(require_permission(Permission.SCHEDULES_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> ScheduleRead:
    updates = body.model_dump(exclude_unset=True)

    try:
        schedule = await schedule_service.update_schedule(
            session,
            schedule_id,
            name=updates.get("name"),
            cron_expression=updates.get("cron_expression"),
            enabled=updates.get("enabled"),
        )
    except CronExpressionError as exc:
        raise _cron_error_to_http(exc) from exc

    if schedule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found")

    scheduler = _get_scheduler(request)

    if scheduler is not None:
        await scheduler.sync_schedule(schedule)

    return schedule  # type: ignore[return-value]


@router.delete(
    "/schedules/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_schedule(
    schedule_id: uuid.UUID,
    request: Request,
    _w: User = Depends(require_permission(Permission.SCHEDULES_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> None:
    deleted = await schedule_service.delete_schedule(session, schedule_id)

    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found")

    scheduler = _get_scheduler(request)

    if scheduler is not None:
        scheduler.remove_schedule_job(schedule_id)


@router.post(
    "/schedules/{schedule_id}/trigger",
    response_model=ScheduleTriggerResult,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_schedule_now(
    schedule_id: uuid.UUID,
    _w: User = Depends(require_permission(Permission.SCHEDULES_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> ScheduleTriggerResult:
    """Manually fire a schedule (same idempotent path as cron)."""

    result = await schedule_service.trigger_scheduled_run(session, schedule_id=schedule_id)

    if result.reason == "not_found":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found")

    return ScheduleTriggerResult(
        triggered=result.triggered,
        reason=result.reason,
        execution_id=result.execution_id,
        fire_at=result.fire_at,
    )
