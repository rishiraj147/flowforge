"""Schedule API and cron trigger tests."""

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


def _create_workflow(client: TestClient, token: str) -> str:
    r = client.post(
        "/workflows",
        headers=_auth(token),
        json={
            "name": "scheduled-wf",
            "definition": {
                "steps": [
                    {"id": "A", "kind": "noop", "needs": []},
                ]
            },
        },
    )

    assert r.status_code == 201, r.text

    return r.json()["id"]


def test_decode_cron_expression():
    app = create_app(Settings(environment="test"))

    with TestClient(app) as client:
        token = _dev_token(client)

        r = client.get(
            "/schedules/cron/decode",
            headers=_auth(token),
            params={"expression": "0 2 * * MON-FRI"},
        )

    assert r.status_code == 200
    body = r.json()

    assert body["expression"] == "0 2 * * MON-FRI"
    assert "MON-FRI" in body["summary"]
    assert len(body["next_runs_utc"]) == 3


def test_create_schedule_rejects_invalid_cron():
    app = create_app(Settings(environment="test"))

    with TestClient(app) as client:
        token = _dev_token(client)
        wf_id = _create_workflow(client, token)

        r = client.post(
            f"/workflows/{wf_id}/schedules",
            headers=_auth(token),
            json={"name": "bad", "cron_expression": "not-a-cron"},
        )

    assert r.status_code == 422


def test_create_and_list_schedules():
    app = create_app(Settings(environment="test"))

    with TestClient(app) as client:
        token = _dev_token(client)
        wf_id = _create_workflow(client, token)

        r = client.post(
            f"/workflows/{wf_id}/schedules",
            headers=_auth(token),
            json={
                "name": "nightly",
                "cron_expression": "0 2 * * *",
                "enabled": True,
            },
        )

        assert r.status_code == 201, r.text
        schedule_id = r.json()["id"]

        r = client.get(
            f"/workflows/{wf_id}/schedules",
            headers=_auth(token),
        )

        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["id"] == schedule_id


@pytest.fixture
def celery_eager():
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True

    yield

    celery_app.conf.task_always_eager = False
    celery_app.conf.task_eager_propagates = False


def test_trigger_schedule_creates_execution(celery_eager):
    app = create_app(Settings(environment="test"))

    with TestClient(app) as client:
        token = _dev_token(client)
        wf_id = _create_workflow(client, token)

        r = client.post(
            f"/workflows/{wf_id}/schedules",
            headers=_auth(token),
            json={"name": "hourly", "cron_expression": "0 * * * *"},
        )

        schedule_id = r.json()["id"]

        r = client.post(
            f"/schedules/{schedule_id}/trigger",
            headers=_auth(token),
        )

        assert r.status_code == 202
        body = r.json()

        assert body["triggered"] is True
        execution_id = body["execution_id"]

        r = client.get(
            f"/executions/{execution_id}",
            headers=_auth(token),
        )

        assert r.status_code == 200
        exec_body = r.json()

        assert exec_body["trigger_source"] == "schedule"
        assert exec_body["schedule_id"] == schedule_id
        assert exec_body["status"] == "success"


def test_trigger_schedule_is_idempotent(celery_eager):
    app = create_app(Settings(environment="test"))

    with TestClient(app) as client:
        token = _dev_token(client)
        wf_id = _create_workflow(client, token)

        r = client.post(
            f"/workflows/{wf_id}/schedules",
            headers=_auth(token),
            json={"name": "hourly", "cron_expression": "0 * * * *"},
        )

        schedule_id = r.json()["id"]

        r1 = client.post(
            f"/schedules/{schedule_id}/trigger",
            headers=_auth(token),
        )

        r2 = client.post(
            f"/schedules/{schedule_id}/trigger",
            headers=_auth(token),
        )

    assert r1.json()["triggered"] is True
    assert r2.json()["triggered"] is False
    assert r2.json()["reason"] == "already_fired"
