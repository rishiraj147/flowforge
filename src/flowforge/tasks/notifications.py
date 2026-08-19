"""Celery tasks for async email delivery."""

import uuid
from typing import Any

from flowforge.celery_app import celery_app
from flowforge.services.notification_service import send_execution_finished_email


@celery_app.task(
    name="flowforge.send_execution_email",
    acks_late=True,
    max_retries=3,
    default_retry_delay=60,
)
def send_execution_email_task(execution_id: str, status: str) -> dict[str, Any]:
    """Send workflow success/failure email off the request/worker hot path."""

    send_execution_finished_email(uuid.UUID(execution_id), status)

    return {
        "execution_id": execution_id,
        "status": status,
        "sent": True,
    }
