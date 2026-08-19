"""Record and replay dead-letter tasks."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowforge.models import DeadLetterTask, Execution, TaskRun


async def record_dead_letter(
    session: AsyncSession,
    *,
    task_run_id: uuid.UUID,
    celery_task_id: str | None,
    task_name: str,
    error: str,
    traceback: str | None,
    retry_count: int,
    payload: dict[str, Any] | None,
) -> DeadLetterTask:
    entry = DeadLetterTask(
        task_run_id=task_run_id,
        celery_task_id=celery_task_id,
        task_name=task_name,
        error=error,
        traceback=traceback,
        retry_count=retry_count,
        payload=payload,
        status="pending",
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)

    return entry


def record_dead_letter_sync(
    *,
    task_run_id: uuid.UUID,
    celery_task_id: str | None,
    task_name: str,
    error: str,
    traceback: str | None,
    retry_count: int,
    payload: dict[str, Any] | None,
) -> uuid.UUID:
    from flowforge.sync_db import sync_session

    session = sync_session()

    try:
        entry = DeadLetterTask(
            task_run_id=task_run_id,
            celery_task_id=celery_task_id,
            task_name=task_name,
            error=error,
            traceback=traceback,
            retry_count=retry_count,
            payload=payload,
            status="pending",
        )
        session.add(entry)
        session.commit()
        session.refresh(entry)

        return entry.id
    finally:
        session.close()


async def list_dead_letter_tasks(
    session: AsyncSession,
    *,
    status: str | None = None,
    limit: int = 50,
) -> list[DeadLetterTask]:
    query = select(DeadLetterTask).order_by(DeadLetterTask.created_at.desc()).limit(limit)

    if status is not None:
        query = query.where(DeadLetterTask.status == status)

    result = await session.execute(query)

    return list(result.scalars().all())


async def get_dead_letter_task(
    session: AsyncSession,
    entry_id: uuid.UUID,
) -> DeadLetterTask | None:
    return await session.get(DeadLetterTask, entry_id)


async def replay_dead_letter(
    session: AsyncSession,
    entry_id: uuid.UUID,
) -> TaskRun | None:
    """Re-queue the underlying task run after a DLQ failure."""

    entry = await session.get(DeadLetterTask, entry_id)

    if entry is None or entry.status != "pending":
        return None

    task_run = await session.get(TaskRun, entry.task_run_id)

    if task_run is None:
        return None

    execution = await session.get(Execution, task_run.execution_id)

    if execution is None:
        return None

    task_run.status = "queued"
    task_run.error = None
    task_run.output = None
    task_run.finished_at = None
    task_run.retry_count = 0

    if execution.status == "failed":
        execution.status = "running"
        execution.finished_at = None

    entry.status = "replayed"
    entry.replayed_at = datetime.now(timezone.utc)

    await session.commit()
    await session.refresh(task_run)

    from flowforge.tasks.execution import execute_step_task

    async_result = execute_step_task.delay(str(task_run.id))
    task_run.celery_task_id = async_result.id

    await session.commit()
    await session.refresh(task_run)

    return task_run
