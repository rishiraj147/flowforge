"""Schedule business logic."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from flowforge.advisory_lock import schedule_lock_pair, try_advisory_xact_lock
from flowforge.cron_parser import (
    CronExpressionError,
    current_fire_time,
    validate_cron_expression,
)
from flowforge.models import Schedule, ScheduleFire, Workflow
from flowforge.services.execution_service import _add_execution, run_execution


@dataclass(frozen=True)
class TriggerScheduledRunResult:
    triggered: bool
    reason: str | None = None
    execution_id: uuid.UUID | None = None
    fire_at: datetime | None = None


async def create_schedule(
    session: AsyncSession,
    *,
    workflow_id: uuid.UUID,
    owner_id: uuid.UUID,
    name: str,
    cron_expression: str,
    enabled: bool = True,
) -> Schedule | None:
    workflow = await session.get(Workflow, workflow_id)

    if workflow is None:
        return None

    expr = validate_cron_expression(cron_expression)

    schedule = Schedule(
        workflow_id=workflow_id,
        owner_id=owner_id,
        name=name,
        cron_expression=expr,
        enabled=enabled,
    )

    session.add(schedule)
    await session.commit()
    await session.refresh(schedule)

    return schedule


async def get_schedule(
    session: AsyncSession,
    schedule_id: uuid.UUID,
) -> Schedule | None:
    return await session.get(Schedule, schedule_id)


async def list_schedules_for_workflow(
    session: AsyncSession,
    workflow_id: uuid.UUID,
) -> list[Schedule] | None:
    workflow = await session.get(Workflow, workflow_id)

    if workflow is None:
        return None

    result = await session.execute(
        select(Schedule)
        .where(Schedule.workflow_id == workflow_id)
        .order_by(Schedule.created_at.asc())
    )

    return list(result.scalars().all())


async def update_schedule(
    session: AsyncSession,
    schedule_id: uuid.UUID,
    *,
    name: str | None = None,
    cron_expression: str | None = None,
    enabled: bool | None = None,
) -> Schedule | None:
    schedule = await session.get(Schedule, schedule_id)

    if schedule is None:
        return None

    if name is not None:
        schedule.name = name

    if cron_expression is not None:
        schedule.cron_expression = validate_cron_expression(cron_expression)

    if enabled is not None:
        schedule.enabled = enabled

    await session.commit()
    await session.refresh(schedule)

    return schedule


async def delete_schedule(
    session: AsyncSession,
    schedule_id: uuid.UUID,
) -> bool:
    schedule = await session.get(Schedule, schedule_id)

    if schedule is None:
        return False

    await session.delete(schedule)
    await session.commit()

    return True


async def trigger_scheduled_run(
    session: AsyncSession,
    *,
    schedule_id: uuid.UUID,
    fire_at: datetime | None = None,
) -> TriggerScheduledRunResult:
    """Fire a schedule once for the current cron slot (idempotent, advisory-locked).

    Step-by-step when cron fires (possibly on 3 API servers simultaneously):

    1. APScheduler job runs on each server at the same wall time.
    2. Each opens a DB transaction and tries pg_try_advisory_xact_lock(schedule).
    3. Only ONE acquires the lock; others skip (leader election per schedule).
    4. Winner computes canonical fire_at for this cron slot.
    5. INSERT schedule_fires(schedule_id, fire_at) — UNIQUE prevents double-fire.
    6. INSERT execution (trigger_source=schedule) in the same transaction.
    7. COMMIT releases the advisory lock.
    8. run_execution() queues the DAG via Celery (outside the lock transaction).
    """

    execution_id: uuid.UUID | None = None
    resolved_fire_at: datetime | None = None

    schedule = await session.get(Schedule, schedule_id)

    if schedule is None:
        return TriggerScheduledRunResult(triggered=False, reason="not_found")

    if not schedule.enabled:
        return TriggerScheduledRunResult(triggered=False, reason="disabled")

    try:
        resolved_fire_at = fire_at or current_fire_time(schedule.cron_expression)
    except CronExpressionError:
        return TriggerScheduledRunResult(triggered=False, reason="invalid_cron")

    key1, key2 = schedule_lock_pair(schedule_id)

    if not await try_advisory_xact_lock(session, key1, key2):
        await session.rollback()
        return TriggerScheduledRunResult(
            triggered=False,
            reason="lock_not_acquired",
        )

    try:
        fire_row = ScheduleFire(
            schedule_id=schedule.id,
            fire_at=resolved_fire_at,
        )
        session.add(fire_row)
        await session.flush()

        execution = await _add_execution(
            session,
            workflow_id=schedule.workflow_id,
            triggered_by=schedule.owner_id,
            trigger_source="schedule",
            schedule_id=schedule.id,
        )

        if execution is None:
            await session.rollback()
            raise RuntimeError(
                f"Workflow {schedule.workflow_id} missing or has no version"
            )

        fire_row.execution_id = execution.id
        schedule.last_triggered_at = resolved_fire_at
        execution_id = execution.id
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return TriggerScheduledRunResult(
            triggered=False,
            reason="already_fired",
            fire_at=resolved_fire_at,
        )

    if execution_id is None:
        return TriggerScheduledRunResult(
            triggered=False,
            reason="not_triggered",
            fire_at=resolved_fire_at,
        )

    await run_execution(session, execution_id)

    return TriggerScheduledRunResult(
        triggered=True,
        execution_id=execution_id,
        fire_at=resolved_fire_at,
    )
