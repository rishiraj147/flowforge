"""Celery autoretry + dead-letter queue tests."""

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from flowforge.authz import Role
from flowforge.celery_app import celery_app
from flowforge.config import Settings
from flowforge.main import create_app
from tests.test_executions import _auth, _dev_token, _promote_in_db, _register_and_login


def _create_flaky_execution(client: TestClient, token: str, fail_until: int) -> str:
    r = client.post(
        "/workflows",
        headers=_auth(token),
        json={
            "name": "flaky-test",
            "definition": {
                "steps": [
                    {
                        "id": "flake",
                        "kind": "flaky",
                        "fail_until_attempt": fail_until,
                    },
                ]
            },
        },
    )

    assert r.status_code == 201, r.text

    wf_id = r.json()["id"]

    r = client.post(
        f"/workflows/{wf_id}/executions",
        headers=_auth(token),
        json={},
    )

    assert r.status_code == 201, r.text

    return r.json()["id"]


@pytest.fixture
def celery_eager():
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True

    yield

    celery_app.conf.task_always_eager = False
    celery_app.conf.task_eager_propagates = False


def test_flaky_step_autoretries_and_succeeds(celery_eager):
    app = create_app(Settings(environment="test"))

    celery_app.conf.task_eager_propagates = False

    try:
        with patch("flowforge.orchestrator.advance_execution"):
            with TestClient(app) as client:
                token = _dev_token(client)
                execution_id = _create_flaky_execution(client, token, fail_until=2)

                r = client.post(
                    f"/executions/{execution_id}/steps/flake/run",
                    headers=_auth(token),
                )

                assert r.status_code == 202, r.text

                task_run_id = r.json()["id"]

                r = client.get(
                    f"/task-runs/{task_run_id}",
                    headers=_auth(token),
                )

                body = r.json()

                assert body["status"] == "success"
                assert body["retry_count"] >= 1
                assert body["output"]["attempt"] == 2
    finally:
        celery_app.conf.task_eager_propagates = True


def test_exhausted_retries_land_in_dead_letter(celery_eager):
    app = create_app(Settings(environment="test"))

    celery_app.conf.task_eager_propagates = False

    try:
        with patch("flowforge.orchestrator.advance_execution"):
            with TestClient(app) as client:
                token = _dev_token(client)
                execution_id = _create_flaky_execution(client, token, fail_until=99)

                r = client.post(
                    f"/executions/{execution_id}/steps/flake/run",
                    headers=_auth(token),
                )

                assert r.status_code == 202

                task_run_id = r.json()["id"]

                r = client.get(
                    f"/task-runs/{task_run_id}",
                    headers=_auth(token),
                )

                assert r.json()["status"] == "failed"

                r = client.get("/dead-letter", headers=_auth(token))

                assert r.status_code == 200
                entries = r.json()

                assert len(entries) >= 1
                assert entries[0]["task_run_id"] == task_run_id
                assert entries[0]["status"] == "pending"
    finally:
        celery_app.conf.task_eager_propagates = True


def test_backoff_preview_endpoint():
    app = create_app(Settings(environment="test"))

    with TestClient(app) as client:
        email = f"u+{uuid.uuid4().hex[:8]}@example.com"
        token = _register_and_login(client, email)

        import asyncio

        asyncio.run(_promote_in_db(email, Role.DEVELOPER))

        r = client.get(
            "/retry-policy/backoff?attempt=3",
            headers=_auth(token),
        )

        assert r.status_code == 200
        body = r.json()

        assert body["delay_without_jitter"] == 240.0
        assert "2^3" in body["formula"]
