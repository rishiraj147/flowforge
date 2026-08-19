"""DAG orchestration — advance execution after each step (sync, for Celery workers)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from flowforge.dag_scheduler import find_ready_steps, is_dag_complete, step_id_str
from flowforge.models import Execution, TaskRun, WorkflowVersion
from flowforge.services.task_run_sync import _now
from flowforge.sync_db import sync_session
from flowforge.tasks.execution import execute_step_task
from flowforge.workflow_events import emit_execution_finished


def _queue_task_run(execution_id: uuid.UUID, step_id: str) -> uuid.UUID | None:
    """Create task_run, commit, enqueue Celery. Returns task_run id or None on conflict."""

    session = sync_session()

    try:
        task_run = TaskRun(
            execution_id=execution_id,
            step_id=step_id,
            status="pending",
        )
        session.add(task_run)

        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            return None

        session.commit()
        task_run_id = task_run.id
    finally:
        session.close()

    async_result = execute_step_task.delay(str(task_run_id))

    session = sync_session()

    try:
        row = session.get(TaskRun, task_run_id)

        if row is None:
            return None

        if row.status == "pending":
            row.status = "queued"

        if row.celery_task_id is None:
            row.celery_task_id = async_result.id

        session.commit()

        return task_run_id
    finally:
        session.close()


def advance_execution(execution_id: uuid.UUID) -> None:
    """Lock execution, queue ready steps, or mark execution terminal.

    Called after every task success (and when POST /executions/{id}/run starts the DAG).
    """

    session = sync_session()
    ready_ids: list[str] = []

    try:
        execution = (
            session.execute(
                select(Execution)
                .where(Execution.id == execution_id)
                .with_for_update()
            )
            .scalar_one_or_none()
        )

        if execution is None:
            return

        if execution.status in ("success", "failed"):
            return

        version = session.get(WorkflowVersion, execution.workflow_version_id)

        if version is None:
            execution.status = "failed"
            execution.finished_at = _now()
            session.commit()
            return

        definition = version.definition

        task_runs = list(
            session.execute(
                select(TaskRun).where(TaskRun.execution_id == execution_id)
            )
            .scalars()
            .all()
        )

        status_by_step = {tr.step_id: tr.status for tr in task_runs}

        if any(status == "failed" for status in status_by_step.values()):
            became_failed = execution.status != "failed"
            execution.status = "failed"
            execution.finished_at = _now()
            session.commit()

            if became_failed:
                from flowforge.metrics import record_execution_completed

                record_execution_completed("failed")
                emit_execution_finished(execution_id, "failed")

            return

        if is_dag_complete(definition, status_by_step):
            became_success = execution.status != "success"
            execution.status = "success"
            execution.finished_at = _now()
            session.commit()

            if became_success:
                from flowforge.metrics import record_execution_completed

                record_execution_completed("success")
                emit_execution_finished(execution_id, "success")

            return

        ready_ids = [step_id_str(step) for step in find_ready_steps(definition, status_by_step)]

        execution.status = "running"
        session.commit()
    finally:
        session.close()

    for step_id in ready_ids:
        _queue_task_run(execution_id, step_id)
