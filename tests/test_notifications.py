"""Email notification tests."""

import uuid
from unittest.mock import patch

from flowforge.config import Settings, get_settings
from flowforge.email_templates import render_execution_email
from flowforge.workflow_events import emit_execution_finished


def test_render_success_template():
    html = render_execution_email(
        "execution_success.html",
        {
            "app_name": "FlowForge",
            "recipient_email": "dev@example.com",
            "recipient_name": "Dev",
            "workflow_name": "daily-etl",
            "execution_id": "abc-123",
            "trigger_source": "manual",
            "finished_at": "2026-08-19T00:00:00+00:00",
        },
    )

    assert "daily-etl" in html
    assert "succeeded" in html.lower()
    assert "abc-123" in html


def test_render_failed_template_with_error():
    html = render_execution_email(
        "execution_failed.html",
        {
            "app_name": "FlowForge",
            "recipient_email": "dev@example.com",
            "recipient_name": None,
            "workflow_name": "daily-etl",
            "execution_id": "abc-123",
            "trigger_source": "schedule",
            "finished_at": "2026-08-19T00:00:00+00:00",
            "error_message": "boom",
        },
    )

    assert "failed" in html.lower()
    assert "boom" in html


@patch("flowforge.tasks.notifications.send_execution_email_task")
def test_emit_execution_finished_queues_celery(mock_task):
    get_settings.cache_clear()
    settings = Settings(email_enabled=True)
    mock_delay = mock_task.delay

    with patch("flowforge.workflow_events.get_settings", return_value=settings):
        execution_id = uuid.uuid4()
        emit_execution_finished(execution_id, "success")

    mock_delay.assert_called_once_with(str(execution_id), "success")
    get_settings.cache_clear()


@patch("flowforge.tasks.notifications.send_execution_email_task")
def test_emit_skipped_when_email_disabled(mock_task):
    get_settings.cache_clear()
    settings = Settings(email_enabled=False)

    with patch("flowforge.workflow_events.get_settings", return_value=settings):
        emit_execution_finished(uuid.uuid4(), "success")

    mock_task.delay.assert_not_called()
    get_settings.cache_clear()


@patch("flowforge.smtp_client._send_via_smtp")
def test_send_execution_finished_email(mock_smtp):
    from flowforge.config import Settings
    from flowforge.models import Execution, User, Workflow
    from flowforge.services.notification_service import send_execution_finished_email
    from flowforge.sync_db import sync_session

    session = sync_session()
    user_email: str

    try:
        user = User(
            email=f"notify+{uuid.uuid4().hex[:8]}@example.com",
            password_hash="x",
            role="developer",
        )
        session.add(user)
        session.flush()
        user_email = user.email

        workflow = Workflow(name="notify-test", owner_id=user.id, status="active")
        session.add(workflow)
        session.flush()

        from flowforge.models.workflow_version import WorkflowVersion

        version = WorkflowVersion(
            workflow_id=workflow.id,
            version_number=1,
            definition={"steps": [{"id": "a", "kind": "noop"}]},
        )
        session.add(version)
        session.flush()

        workflow.current_version_id = version.id

        execution = Execution(
            workflow_id=workflow.id,
            workflow_version_id=version.id,
            status="success",
            triggered_by=user.id,
            trigger_source="manual",
        )
        session.add(execution)
        session.commit()

        execution_id = execution.id
    finally:
        session.close()

    with patch(
        "flowforge.smtp_client.get_settings",
        return_value=Settings(email_enabled=True),
    ):
        send_execution_finished_email(execution_id, "success")

    mock_smtp.assert_called_once()
    assert mock_smtp.call_args.kwargs["to_email"] == user_email
