"""Execution and task-run API tests."""

import asyncio
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from flowforge.authz import Role
from flowforge.celery_app import celery_app
from flowforge.config import Settings, get_settings
from flowforge.db import create_engine, create_sessionmaker
from flowforge.main import create_app
from flowforge.models import User


def _new_email() -> str:
    return f"u+{uuid.uuid4().hex[:8]}@example.com"


def _register_and_login(client: TestClient, email: str) -> str:
    client.post(
        "/auth/register",
        json={"email": email, "password": "supersecret123"},
    )
    r = client.post(
        "/auth/login",
        json={"email": email, "password": "supersecret123"},
    )

    return r.json()["access_token"]


async def _promote_in_db(email: str, role: Role) -> None:
    engine = create_engine(get_settings())
    Session = create_sessionmaker(engine)

    async with Session() as session:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one()
        user.role = role.value
        await session.commit()

    await engine.dispose()


def _dev_token(client: TestClient) -> str:
    email = _new_email()
    token = _register_and_login(client, email)
    asyncio.run(_promote_in_db(email, Role.DEVELOPER))

    return token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_workflow_with_noop_step(client: TestClient, token: str) -> tuple[str, str]:
    r = client.post(
        "/workflows",
        headers=_auth(token),
        json={
            "name": "exec-test",
            "definition": {
                "steps": [
                    {"id": "welcome", "kind": "noop"},
                ]
            },
        },
    )

    assert r.status_code == 201, r.text

    wf_id = r.json()["id"]

    r = client.post(
        f"/workflows/{wf_id}/executions",
        headers=_auth(token),
    )

    assert r.status_code == 201, r.text

    return wf_id, r.json()["id"]


CHAIN_DEFINITION = {
    "steps": [
        {"id": "A", "kind": "noop", "needs": []},
        {"id": "B", "kind": "noop", "needs": ["A"]},
        {"id": "C", "kind": "noop", "needs": ["B"]},
    ]
}


def _create_chain_execution(client: TestClient, token: str) -> str:
    r = client.post(
        "/workflows",
        headers=_auth(token),
        json={"name": "chain-exec", "definition": CHAIN_DEFINITION},
    )

    assert r.status_code == 201, r.text

    wf_id = r.json()["id"]

    r = client.post(
        f"/workflows/{wf_id}/executions",
        headers=_auth(token),
    )

    assert r.status_code == 201, r.text

    return r.json()["id"]


def test_run_step_queues_celery_task():
    app = create_app(Settings(environment="test"))

    mock_result = MagicMock()
    mock_result.id = "celery-abc"

    with patch(
        "flowforge.services.execution_service.execute_step_task.delay",
        return_value=mock_result,
    ) as mock_delay:
        with TestClient(app) as client:
            token = _dev_token(client)
            _, execution_id = _create_workflow_with_noop_step(client, token)

            r = client.post(
                f"/executions/{execution_id}/steps/welcome/run",
                headers=_auth(token),
            )

    assert r.status_code == 202
    body = r.json()

    assert body["status"] == "queued"
    assert body["step_id"] == "welcome"
    assert body["celery_task_id"] == "celery-abc"
    mock_delay.assert_called_once()


def test_get_task_run_returns_status():
    app = create_app(Settings(environment="test"))

    mock_result = MagicMock()
    mock_result.id = "celery-xyz"

    with patch(
        "flowforge.services.execution_service.execute_step_task.delay",
        return_value=mock_result,
    ):
        with TestClient(app) as client:
            token = _dev_token(client)
            _, execution_id = _create_workflow_with_noop_step(client, token)

            r = client.post(
                f"/executions/{execution_id}/steps/welcome/run",
                headers=_auth(token),
            )

            task_run_id = r.json()["id"]

            r = client.get(
                f"/task-runs/{task_run_id}",
                headers=_auth(token),
            )

    assert r.status_code == 200
    assert r.json()["id"] == task_run_id
    assert r.json()["status"] == "queued"


def test_run_invalid_step_returns_404():
    app = create_app(Settings(environment="test"))

    with TestClient(app) as client:
        token = _dev_token(client)
        _, execution_id = _create_workflow_with_noop_step(client, token)

        r = client.post(
            f"/executions/{execution_id}/steps/not-a-step/run",
            headers=_auth(token),
        )

    assert r.status_code == 404


@pytest.fixture
def celery_eager():
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True

    yield

    celery_app.conf.task_always_eager = False
    celery_app.conf.task_eager_propagates = False


def test_eager_execution_completes_task_run(celery_eager):
    """With eager mode, worker runs in-process; DB should reach success."""

    app = create_app(Settings(environment="test"))

    with TestClient(app) as client:
        token = _dev_token(client)
        _, execution_id = _create_workflow_with_noop_step(client, token)

        r = client.post(
            f"/executions/{execution_id}/steps/welcome/run",
            headers=_auth(token),
        )

        assert r.status_code == 202

        task_run_id = r.json()["id"]

        r = client.get(
            f"/task-runs/{task_run_id}",
            headers=_auth(token),
        )

        assert r.status_code == 200
        body = r.json()

        assert body["status"] == "success"
        assert body["output"]["kind"] == "noop"

        r = client.get(
            f"/executions/{execution_id}",
            headers=_auth(token),
        )

        assert r.json()["status"] == "success"


def test_run_step_before_dependencies_returns_409():
    app = create_app(Settings(environment="test"))

    with TestClient(app) as client:
        token = _dev_token(client)
        execution_id = _create_chain_execution(client, token)

        r = client.post(
            f"/executions/{execution_id}/steps/C/run",
            headers=_auth(token),
        )

    assert r.status_code == 409
    detail = r.json()["detail"]

    assert detail["code"] == "dependencies_not_met"
    assert "B" in detail["unsatisfied_dependencies"]


def test_run_step_chain_in_order(celery_eager):
    """Manual A → B → C without orchestrator auto-queueing downstream steps."""

    app = create_app(Settings(environment="test"))

    with patch("flowforge.orchestrator.advance_execution"):
        with TestClient(app) as client:
            token = _dev_token(client)
            execution_id = _create_chain_execution(client, token)

            for step_id in ("A", "B", "C"):
                r = client.post(
                    f"/executions/{execution_id}/steps/{step_id}/run",
                    headers=_auth(token),
                )

                assert r.status_code == 202, r.text
                assert r.json()["step_id"] == step_id

            r = client.get(
                f"/executions/{execution_id}/task-runs",
                headers=_auth(token),
            )

            by_step = {tr["step_id"]: tr["status"] for tr in r.json()}

            assert by_step == {"A": "success", "B": "success", "C": "success"}


def test_run_completed_step_returns_409(celery_eager):
    app = create_app(Settings(environment="test"))

    with patch("flowforge.orchestrator.advance_execution"):
        with TestClient(app) as client:
            token = _dev_token(client)
            _, execution_id = _create_workflow_with_noop_step(client, token)

            r = client.post(
                f"/executions/{execution_id}/steps/welcome/run",
                headers=_auth(token),
            )

            assert r.status_code == 202

            r = client.post(
                f"/executions/{execution_id}/steps/welcome/run",
                headers=_auth(token),
            )

    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "already_completed"


def test_retry_failed_step(celery_eager):
    app = create_app(Settings(environment="test"))

    celery_app.conf.task_eager_propagates = False

    try:
        with patch(
            "flowforge.services.task_run_sync.run_step",
            side_effect=[
                ValueError("boom"),
                {"kind": "noop", "step_id": "welcome", "status": "ok"},
            ],
        ):
            with patch("flowforge.orchestrator.advance_execution"):
                with TestClient(app) as client:
                    token = _dev_token(client)
                    _, execution_id = _create_workflow_with_noop_step(client, token)

                    r = client.post(
                        f"/executions/{execution_id}/steps/welcome/run",
                        headers=_auth(token),
                    )

                    assert r.status_code == 202

                    task_run_id = r.json()["id"]

                    r = client.get(
                        f"/task-runs/{task_run_id}",
                        headers=_auth(token),
                    )

                    assert r.json()["status"] == "failed"

                    r = client.post(
                        f"/executions/{execution_id}/steps/welcome/run",
                        headers=_auth(token),
                    )

                    assert r.status_code == 202

                    r = client.get(
                        f"/task-runs/{task_run_id}",
                        headers=_auth(token),
                    )

                    assert r.json()["status"] == "success"
    finally:
        celery_app.conf.task_eager_propagates = True
