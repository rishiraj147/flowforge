"""Workflow lifecycle events — notification service listens here.

Emitters call these after Postgres commits so listeners see durable state.
Delivery is async via Celery (never block the worker/API on SMTP).
"""

from __future__ import annotations

import logging
import uuid

from flowforge.config import get_settings

logger = logging.getLogger(__name__)


def emit_execution_finished(execution_id: uuid.UUID, status: str) -> None:
    """Queue an email when an execution reaches a terminal state."""

    if status not in ("success", "failed"):
        return

    settings = get_settings()

    if not settings.email_enabled:
        return

    from flowforge.tasks.notifications import send_execution_email_task

    logger.info(
        "Queueing execution notification: execution_id=%s status=%s",
        execution_id,
        status,
    )
    send_execution_email_task.delay(str(execution_id), status)
