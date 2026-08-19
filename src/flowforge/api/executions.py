"""Execution and task-run REST endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from flowforge.authz import Permission, require_permission
from flowforge.db import get_session
from flowforge.models import User
from flowforge.schemas.execution import ExecutionRead, TaskRunRead
from flowforge.services import execution_service
from flowforge.services.execution_service import QueueStepRunError

router = APIRouter(tags=["executions"])


@router.post(
    "/workflows/{workflow_id}/executions",
    response_model=ExecutionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_execution(
    workflow_id: uuid.UUID,
    _w: User = Depends(require_permission(Permission.EXECUTIONS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> ExecutionRead:
    """Create an execution pinned to the workflow's current immutable version."""

    execution = await execution_service.create_execution(
        session,
        workflow_id=workflow_id,
        triggered_by=_w.id,
    )

    if execution is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Workflow not found or has no version",
        )

    return execution  # type: ignore[return-value]


@router.get(
    "/executions/{execution_id}",
    response_model=ExecutionRead,
)
async def get_execution(
    execution_id: uuid.UUID,
    _r: User = Depends(require_permission(Permission.EXECUTIONS_READ)),
    session: AsyncSession = Depends(get_session),
) -> ExecutionRead:
    execution = await execution_service.get_execution(session, execution_id)

    if execution is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found")

    return execution  # type: ignore[return-value]


@router.post(
    "/executions/{execution_id}/run",
    response_model=ExecutionRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_execution(
    execution_id: uuid.UUID,
    _w: User = Depends(require_permission(Permission.EXECUTIONS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> ExecutionRead:
    """Run the full DAG — queues wave 0, then each wave after dependencies complete."""

    execution = await execution_service.run_execution(session, execution_id)

    if execution is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found")

    return execution  # type: ignore[return-value]


@router.get(
    "/executions/{execution_id}/task-runs",
    response_model=list[TaskRunRead],
)
async def list_execution_task_runs(
    execution_id: uuid.UUID,
    _r: User = Depends(require_permission(Permission.EXECUTIONS_READ)),
    session: AsyncSession = Depends(get_session),
) -> list[TaskRunRead]:
    task_runs = await execution_service.list_task_runs(session, execution_id)

    if task_runs is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found")

    return task_runs  # type: ignore[return-value]


@router.post(
    "/executions/{execution_id}/steps/{step_id}/run",
    response_model=TaskRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_execution_step(
    execution_id: uuid.UUID,
    step_id: str,
    _w: User = Depends(require_permission(Permission.EXECUTIONS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> TaskRunRead:
    """Queue one step when all dependencies succeeded (or retry a failed step)."""

    try:
        task_run = await execution_service.queue_step_run(
            session,
            execution_id=execution_id,
            step_id=step_id,
        )
    except QueueStepRunError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "code": exc.code,
                "message": exc.message,
                "unsatisfied_dependencies": exc.unsatisfied_dependencies,
            },
        ) from exc

    if task_run is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Execution not found or step id invalid for this version",
        )

    return task_run  # type: ignore[return-value]


@router.get(
    "/task-runs/{task_run_id}",
    response_model=TaskRunRead,
)
async def get_task_run(
    task_run_id: uuid.UUID,
    _r: User = Depends(require_permission(Permission.EXECUTIONS_READ)),
    session: AsyncSession = Depends(get_session),
) -> TaskRunRead:
    task_run = await execution_service.get_task_run(session, task_run_id)

    if task_run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task run not found")

    return task_run  # type: ignore[return-value]
