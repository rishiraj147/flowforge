"""Sync DB updates for task runs — used from Celery tasks and signals."""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from flowforge.log_emitter import TaskRunLogEmitter
from flowforge.metrics import duration_since, record_task_run_finished
from flowforge.models import Execution, TaskRun, WorkflowVersion
from flowforge.step_runner import find_step, run_step
from flowforge.sync_db import sync_session


def _publish_task_run_status(
    session: Session,
    task_run: TaskRun,
    status: str,
    error: str | None = None,
) -> None:
    execution = session.get(Execution, task_run.execution_id)

    if execution is None:
        return

    TaskRunLogEmitter(
        execution.id,
        task_run.id,
        task_run.step_id,
    ).status(status, error=error)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def load_task_run_context(
    session: Session,
    task_run_id: uuid.UUID,
) -> tuple[TaskRun, dict[str, Any], Execution]:
    """Load task run, parent execution, and step definition from frozen version."""

    task_run = session.get(TaskRun, task_run_id)

    if task_run is None:
        raise ValueError(f"TaskRun {task_run_id} not found")

    execution = session.get(Execution, task_run.execution_id)

    if execution is None:
        raise ValueError(f"Execution {task_run.execution_id} not found")

    version = session.get(WorkflowVersion, execution.workflow_version_id)

    if version is None:
        raise ValueError(f"WorkflowVersion {execution.workflow_version_id} not found")

    step = find_step(version.definition, task_run.step_id)

    if step is None:
        raise ValueError(
            f"Step {task_run.step_id!r} not found in workflow version {version.id}"
        )

    return task_run, step, execution


def _step_kind_for_task_run(session: Session, task_run: TaskRun) -> str:
    execution = session.get(Execution, task_run.execution_id)

    if execution is None:
        return "unknown"

    version = session.get(WorkflowVersion, execution.workflow_version_id)

    if version is None:
        return "unknown"

    step = find_step(version.definition, task_run.step_id)

    if step is None:
        return "unknown"

    return str(step.get("kind", "noop"))


def mark_task_run_running(task_run_id: uuid.UUID, celery_task_id: str) -> None:
    """pending|queued → running (idempotent if already success)."""

    session = sync_session()

    try:
        task_run = session.get(TaskRun, task_run_id)

        if task_run is None:
            return

        if task_run.status in ("success", "failed"):
            return

        if task_run.status in ("pending", "queued"):
            task_run.status = "running"
            task_run.started_at = _now()
            task_run.celery_task_id = celery_task_id
            _publish_task_run_status(session, task_run, "running")

        session.commit()
    finally:
        session.close()


def mark_task_run_success(
    task_run_id: uuid.UUID,
    output: dict[str, Any],
    celery_task_id: str,
) -> None:
    session = sync_session()
    execution_id: uuid.UUID | None = None

    try:
        task_run = session.get(TaskRun, task_run_id)

        if task_run is None:
            return

        if task_run.status == "success":
            return

        started_at = task_run.started_at
        step_kind = _step_kind_for_task_run(session, task_run)

        task_run.status = "success"
        task_run.output = output
        task_run.error = None
        task_run.finished_at = _now()
        task_run.celery_task_id = celery_task_id
        execution_id = task_run.execution_id
        _publish_task_run_status(session, task_run, "success")

        session.commit()

        record_task_run_finished(
            step_kind=step_kind,
            status="success",
            duration_seconds=duration_since(started_at),
        )
    finally:
        session.close()

    if execution_id is not None:
        from flowforge.orchestrator import advance_execution

        advance_execution(execution_id)


def mark_task_run_failed(
    task_run_id: uuid.UUID,
    error: str,
    celery_task_id: str,
) -> None:
    session = sync_session()

    try:
        task_run = session.get(TaskRun, task_run_id)

        if task_run is None:
            return

        if task_run.status == "failed":
            return

        started_at = task_run.started_at
        step_kind = _step_kind_for_task_run(session, task_run)

        task_run.status = "failed"
        task_run.error = error
        task_run.finished_at = _now()
        task_run.celery_task_id = celery_task_id

        execution = session.get(Execution, task_run.execution_id)
        notify_failed = False

        if execution is not None and execution.status != "failed":
            execution.status = "failed"
            execution.finished_at = _now()
            notify_failed = True

        _publish_task_run_status(session, task_run, "failed", error=error)

        session.commit()

        record_task_run_finished(
            step_kind=step_kind,
            status="failed",
            duration_seconds=duration_since(started_at),
        )

        if notify_failed and execution is not None:
            from flowforge.metrics import record_execution_completed
            from flowforge.workflow_events import emit_execution_finished

            record_execution_completed("failed")
            emit_execution_finished(execution.id, "failed")
    finally:
        session.close()


def mark_task_run_retrying(
    task_run_id: uuid.UUID,
    celery_task_id: str,
    retry_count: int,
    reason: str | None = None,
) -> None:
    session = sync_session()

    try:
        task_run = session.get(TaskRun, task_run_id)

        if task_run is None:
            return

        task_run.status = "running"
        task_run.retry_count = retry_count
        task_run.celery_task_id = celery_task_id
        task_run.error = reason
        task_run.finished_at = None

        message = f"Retry #{retry_count} scheduled"

        if reason:
            message = f"{message}: {reason}"

        emitter = TaskRunLogEmitter(
            task_run.execution_id,
            task_run.id,
            task_run.step_id,
        )
        emitter.log(message, level="warning")
        _publish_task_run_status(session, task_run, "running")

        session.commit()
    finally:
        session.close()


def execute_task_run(task_run_id: uuid.UUID, attempt: int = 0) -> dict[str, Any]:
    """Load context, run step logic, return output (signals update DB on success/failure)."""

    session = sync_session()

    try:
        task_run, step, execution = load_task_run_context(session, task_run_id)

        if task_run.status == "success":
            return task_run.output or {}

        emitter = TaskRunLogEmitter(
            execution.id,
            task_run.id,
            task_run.step_id,
        )

        from flowforge.services.artifact_service import store_artifact_sync

        def upload_artifact(data: bytes, filename: str, content_type: str | None) -> uuid.UUID:
            return store_artifact_sync(
                data=data,
                filename=filename,
                content_type=content_type,
                uploaded_by=execution.triggered_by,
                execution_id=execution.id,
                task_run_id=task_run.id,
            )

        return run_step(
            step,
            log=emitter.log,
            artifact_upload=upload_artifact,
            attempt=attempt,
        )
    finally:
        session.close()
