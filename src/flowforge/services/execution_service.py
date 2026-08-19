"""Execution business logic (async API layer)."""

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from flowforge.dag_scheduler import check_manual_step_run
from flowforge.models import Execution, TaskRun, Workflow, WorkflowVersion
from flowforge.orchestrator import advance_execution
from flowforge.step_runner import find_step
from flowforge.tasks.execution import execute_step_task


class QueueStepRunError(Exception):
    """queue_step_run rejected — map to 409 (or execution_completed) in the API."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        unsatisfied_dependencies: list[str] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.unsatisfied_dependencies = unsatisfied_dependencies or []
        super().__init__(message)


async def create_execution(
    session: AsyncSession,
    *,
    workflow_id: uuid.UUID,
    triggered_by: uuid.UUID,
    trigger_source: str = "manual",
    schedule_id: uuid.UUID | None = None,
    webhook_id: uuid.UUID | None = None,
) -> Execution | None:
    """Start an execution pinned to the workflow's current version."""

    execution = await _add_execution(
        session,
        workflow_id=workflow_id,
        triggered_by=triggered_by,
        trigger_source=trigger_source,
        schedule_id=schedule_id,
        webhook_id=webhook_id,
    )

    if execution is None:
        return None

    await session.commit()
    await session.refresh(execution)

    return execution


async def _add_execution(
    session: AsyncSession,
    *,
    workflow_id: uuid.UUID,
    triggered_by: uuid.UUID,
    trigger_source: str = "manual",
    schedule_id: uuid.UUID | None = None,
    webhook_id: uuid.UUID | None = None,
) -> Execution | None:
    """Insert execution row without committing (for transactional triggers)."""

    result = await session.execute(
        select(Workflow)
        .where(Workflow.id == workflow_id)
        .options(selectinload(Workflow.current_version))
    )
    workflow = result.scalar_one_or_none()

    if workflow is None or workflow.current_version_id is None:
        return None

    execution = Execution(
        workflow_id=workflow.id,
        workflow_version_id=workflow.current_version_id,
        status="pending",
        triggered_by=triggered_by,
        trigger_source=trigger_source,
        schedule_id=schedule_id,
        webhook_id=webhook_id,
    )

    session.add(execution)
    await session.flush()

    from flowforge.metrics import record_workflow_triggered

    record_workflow_triggered(trigger_source)

    return execution


async def get_execution(
    session: AsyncSession,
    execution_id: uuid.UUID,
) -> Execution | None:
    return await session.get(Execution, execution_id)


async def queue_step_run(
    session: AsyncSession,
    *,
    execution_id: uuid.UUID,
    step_id: str,
) -> TaskRun | None:
    """Queue one step when dependencies are satisfied (or retry a failed step)."""

    execution = await session.get(Execution, execution_id)

    if execution is None:
        return None

    if execution.status == "success":
        raise QueueStepRunError(
            "execution_completed",
            "Execution already completed",
        )

    version = await session.get(WorkflowVersion, execution.workflow_version_id)

    if version is None:
        return None

    step = find_step(version.definition, step_id)

    if step is None:
        return None

    result = await session.execute(
        select(TaskRun).where(TaskRun.execution_id == execution_id)
    )
    existing_runs = list(result.scalars().all())
    status_by_step = {tr.step_id: tr.status for tr in existing_runs}
    existing = next((tr for tr in existing_runs if tr.step_id == step_id), None)

    check = check_manual_step_run(step, status_by_step)

    if not check.allowed:
        raise QueueStepRunError(
            check.error_code or "step_not_runnable",
            check.message or "Step cannot be run",
            unsatisfied_dependencies=check.unsatisfied_dependencies,
        )

    if existing is not None:
        existing.status = "pending"
        existing.error = None
        existing.output = None
        existing.started_at = None
        existing.finished_at = None
        existing.celery_task_id = None
        task_run = existing
    else:
        task_run = TaskRun(
            execution_id=execution.id,
            step_id=step_id,
            status="pending",
        )
        session.add(task_run)

    if execution.status == "failed":
        execution.status = "running"
        execution.finished_at = None
    # Commit BEFORE delay() so the worker (sync session / eager mode) can read the row.
    await session.commit()
    await session.refresh(task_run)

    async_result = execute_step_task.delay(str(task_run.id))

    await session.refresh(task_run)

    if task_run.status == "pending":
        task_run.status = "queued"

    if task_run.celery_task_id is None:
        task_run.celery_task_id = async_result.id
        await session.commit()
        await session.refresh(task_run)

    return task_run


async def get_task_run(
    session: AsyncSession,
    task_run_id: uuid.UUID,
) -> TaskRun | None:
    return await session.get(TaskRun, task_run_id)


async def list_task_runs(
    session: AsyncSession,
    execution_id: uuid.UUID,
) -> list[TaskRun] | None:
    execution = await session.get(Execution, execution_id)

    if execution is None:
        return None

    result = await session.execute(
        select(TaskRun)
        .where(TaskRun.execution_id == execution_id)
        .order_by(TaskRun.created_at.asc())
    )

    return list(result.scalars().all())


async def run_execution(
    session: AsyncSession,
    execution_id: uuid.UUID,
) -> Execution | None:
    """Start (or resume) full DAG execution — queues all currently-ready steps."""

    execution = await session.get(Execution, execution_id)

    if execution is None:
        return None

    if execution.status in ("success", "failed"):
        return execution

    if execution.status == "pending":
        execution.status = "running"
        await session.commit()
        await session.refresh(execution)

    await asyncio.to_thread(advance_execution, execution_id)

    await session.refresh(execution)

    return execution
