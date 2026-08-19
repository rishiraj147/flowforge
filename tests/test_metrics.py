"""Prometheus /metrics endpoint tests."""

from flowforge.config import Settings
from flowforge.main import create_app
from fastapi.testclient import TestClient


def test_metrics_disabled_by_default_in_test_env():
    app = create_app(Settings(environment="test"))

    with TestClient(app) as client:
        response = client.get("/metrics")

    assert response.status_code == 404


def test_metrics_endpoint_exposes_custom_metrics():
    app = create_app(Settings(environment="test", metrics_enabled=True))

    with TestClient(app) as client:
        response = client.get("/metrics")

    assert response.status_code == 200
    body = response.text

    assert "workflows_triggered_total" in body
    assert "task_duration_seconds" in body
    assert "executions_completed_total" in body
    assert "task_runs_total" in body
    assert "http_requests_total" in body


def test_record_workflow_triggered_increments_counter():
    from flowforge.metrics import WORKFLOWS_TRIGGERED_TOTAL, record_workflow_triggered

    before = WORKFLOWS_TRIGGERED_TOTAL.labels(trigger_source="manual")._value.get()

    record_workflow_triggered("manual")

    after = WORKFLOWS_TRIGGERED_TOTAL.labels(trigger_source="manual")._value.get()

    assert after == before + 1
