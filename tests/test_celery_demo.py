"""Tests for Celery demo queue endpoint."""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from flowforge.config import Settings
from flowforge.main import create_app


def test_demo_slow_queues_task_without_blocking():
    app = create_app(Settings(environment="test"))

    mock_result = MagicMock()
    mock_result.id = "fake-task-id-123"

    with patch(
        "flowforge.api.demo.demo_slow_task.delay",
        return_value=mock_result,
    ) as mock_delay:
        with TestClient(app) as client:
            r = client.post("/demo/slow?seconds=10")

    assert r.status_code == 200
    assert r.json() == {
        "queued": True,
        "task_id": "fake-task-id-123",
    }
    mock_delay.assert_called_once_with(10)


def test_demo_slow_accepts_custom_seconds():
    app = create_app(Settings(environment="test"))

    mock_result = MagicMock()
    mock_result.id = "another-id"

    with patch(
        "flowforge.api.demo.demo_slow_task.delay",
        return_value=mock_result,
    ) as mock_delay:
        with TestClient(app) as client:
            r = client.post("/demo/slow?seconds=3")

    assert r.status_code == 200
    mock_delay.assert_called_once_with(3)


def test_demo_slow_rejects_invalid_seconds():
    app = create_app(Settings(environment="test"))

    with TestClient(app) as client:
        r = client.post("/demo/slow?seconds=0")

    assert r.status_code == 422
