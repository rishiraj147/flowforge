"""Celery task: execute a single workflow step (Step 2.5 + 4.3 retries)."""

import uuid
from typing import Any

from celery import current_task
from celery.signals import task_failure, task_prerun, task_retry, task_success

from flowforge.celery_app import celery_app
from flowforge.exceptions import PermanentStepError, TransientStepError
from flowforge.services.dead_letter_service import record_dead_letter_sync
from flowforge.services.task_run_sync import (
    execute_task_run,
    mark_task_run_failed,
    mark_task_run_retrying,
    mark_task_run_running,
    mark_task_run_success,
)


@celery_app.task(
    bind=True,
    name="flowforge.execute_step",
    acks_late=True,
    reject_on_worker_lost=True,
    autoretry_for=(TransientStepError,),
    dont_autoretry_for=(PermanentStepError,),
    retry_backoff=30,
    retry_backoff_max=240,
    retry_jitter=True,
    max_retries=4,
)
def execute_step_task(self, task_run_id: str) -> dict[str, Any]:
    """Run one step for a task_run row. DB lifecycle handled by signals."""

    return execute_task_run(
        uuid.UUID(task_run_id),
        attempt=self.request.retries,
    )


@task_prerun.connect(sender=execute_step_task)
def on_execute_step_prerun(
    sender: object = None,
    task_id: str | None = None,
    args: tuple[object, ...] | None = None,
    **kwargs: object,
) -> None:
    if not args or task_id is None:
        return

    mark_task_run_running(uuid.UUID(str(args[0])), celery_task_id=task_id)


@task_retry.connect(sender=execute_step_task)
def on_execute_step_retry(
    sender: object = None,
    request: object = None,
    reason: object = None,
    einfo: object = None,
    **kwargs: object,
) -> None:
    if request is None or not getattr(request, "args", None):
        return

    mark_task_run_retrying(
        uuid.UUID(str(request.args[0])),
        celery_task_id=request.id,
        retry_count=request.retries,
        reason=str(reason) if reason is not None else None,
    )


@task_success.connect(sender=execute_step_task)
def on_execute_step_success(
    sender: object = None,
    result: object = None,
    **kwargs: object,
) -> None:
    """Celery 5 sends only sender + result — read args/id from current_task."""

    if current_task is None or current_task.request is None:
        return

    args = current_task.request.args

    if not args:
        return

    output = result if isinstance(result, dict) else {"result": result}

    mark_task_run_success(
        uuid.UUID(str(args[0])),
        output=output,
        celery_task_id=current_task.request.id,
    )


@task_failure.connect(sender=execute_step_task)
def on_execute_step_failure(
    sender: object = None,
    task_id: str | None = None,
    exception: BaseException | None = None,
    args: tuple[object, ...] | None = None,
    einfo: object = None,
    **kwargs: object,
) -> None:
    if not args or task_id is None or exception is None:
        return

    task_run_id = uuid.UUID(str(args[0]))
    retry_count = 0

    if current_task is not None and current_task.request is not None:
        retry_count = current_task.request.retries

    record_dead_letter_sync(
        task_run_id=task_run_id,
        celery_task_id=task_id,
        task_name="flowforge.execute_step",
        error=str(exception),
        traceback=str(einfo) if einfo is not None else None,
        retry_count=retry_count,
        payload={"task_run_id": str(task_run_id)},
    )

    mark_task_run_failed(
        task_run_id,
        error=str(exception),
        celery_task_id=task_id,
    )
