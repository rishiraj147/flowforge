"""Emit structured log events from sync worker code."""

from __future__ import annotations

import uuid

from flowforge.log_channels import LogLevel, log_event, status_event
from flowforge.log_publisher import publish_execution_log


class TaskRunLogEmitter:
    """Publishes log + status events for one task run to Redis."""

    def __init__(
        self,
        execution_id: uuid.UUID,
        task_run_id: uuid.UUID,
        step_id: str,
    ) -> None:
        self._execution_id = execution_id
        self._task_run_id = task_run_id
        self._step_id = step_id

    def log(self, message: str, level: LogLevel = "info") -> None:
        publish_execution_log(
            self._execution_id,
            log_event(
                execution_id=self._execution_id,
                task_run_id=self._task_run_id,
                step_id=self._step_id,
                message=message,
                level=level,
            ),
        )

    def status(self, status: str, error: str | None = None) -> None:
        publish_execution_log(
            self._execution_id,
            status_event(
                execution_id=self._execution_id,
                task_run_id=self._task_run_id,
                step_id=self._step_id,
                status=status,
                error=error,
            ),
        )
