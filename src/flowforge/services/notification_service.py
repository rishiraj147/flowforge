"""Notification service — builds emails from workflow events."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from flowforge.config import get_settings
from flowforge.email_templates import render_execution_email
from flowforge.models import Execution, TaskRun, User, Workflow
from flowforge.smtp_client import send_html_email
from flowforge.sync_db import sync_session


def _format_timestamp(value) -> str:
    if value is None:
        return "—"

    return value.isoformat()


def send_execution_finished_email(execution_id: uuid.UUID, status: str) -> None:
    """Load execution context and send one notification email (sync worker)."""

    session = sync_session()

    try:
        execution = session.get(Execution, execution_id)

        if execution is None:
            return

        if execution.status != status:
            return

        user = session.get(User, execution.triggered_by)

        if user is None:
            return

        workflow = session.get(Workflow, execution.workflow_id)

        workflow_name = workflow.name if workflow is not None else "Workflow"

        error_message: str | None = None

        if status == "failed":
            failed_run = session.execute(
                select(TaskRun)
                .where(
                    TaskRun.execution_id == execution_id,
                    TaskRun.status == "failed",
                )
                .order_by(TaskRun.finished_at.desc().nullslast())
                .limit(1)
            ).scalar_one_or_none()

            if failed_run is not None:
                error_message = failed_run.error

        settings = get_settings()

        context = {
            "app_name": settings.app_name,
            "recipient_email": user.email,
            "recipient_name": user.full_name,
            "workflow_name": workflow_name,
            "execution_id": str(execution.id),
            "trigger_source": execution.trigger_source,
            "finished_at": _format_timestamp(execution.finished_at),
            "error_message": error_message,
        }

        if status == "success":
            subject = f"[FlowForge] {workflow_name} succeeded"
            html = render_execution_email("execution_success.html", context)
        else:
            subject = f"[FlowForge] {workflow_name} failed"
            html = render_execution_email("execution_failed.html", context)

        send_html_email(
            to_email=user.email,
            subject=subject,
            html_body=html,
            text_body=f"Workflow {workflow_name} — execution {execution.id} — {status}",
        )
    finally:
        session.close()
