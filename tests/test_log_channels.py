"""Log channel payload tests."""

import uuid

from flowforge.log_channels import execution_log_channel, log_event, status_event


def test_execution_log_channel_format():
    eid = uuid.uuid4()

    assert execution_log_channel(eid) == f"flowforge:logs:execution:{eid}"


def test_log_event_shape():
    eid = uuid.uuid4()
    trid = uuid.uuid4()

    event = log_event(
        execution_id=eid,
        task_run_id=trid,
        step_id="A",
        message="hello",
        level="info",
    )

    assert event["type"] == "log"
    assert event["message"] == "hello"
    assert event["execution_id"] == str(eid)


def test_status_event_includes_error():
    event = status_event(
        execution_id=uuid.uuid4(),
        task_run_id=uuid.uuid4(),
        step_id="A",
        status="failed",
        error="boom",
    )

    assert event["type"] == "status"
    assert event["error"] == "boom"
