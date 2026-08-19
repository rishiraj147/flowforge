"""WebSocket log streaming integration tests."""

import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from flowforge.authz import Role
from flowforge.celery_app import celery_app
from flowforge.config import Settings, get_settings
from flowforge.db import create_engine, create_sessionmaker
from flowforge.log_channels import execution_log_channel
from flowforge.log_publisher import publish_execution_log
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


def _create_sleep_execution(client: TestClient, token: str, seconds: int = 2) -> str:
    r = client.post(
        "/workflows",
        headers=_auth(token),
        json={
            "name": "log-stream-wf",
            "definition": {
                "steps": [
                    {"id": "wait", "kind": "sleep", "seconds": seconds},
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

    return r.json()["id"]


@pytest.fixture
def celery_eager():
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True

    yield

    celery_app.conf.task_always_eager = False
    celery_app.conf.task_eager_propagates = False


def _test_settings() -> Settings:
    return Settings(
        environment="test",
        log_stream_heartbeat_seconds=3600,
    )


def test_websocket_receives_published_log():
    app = create_app(_test_settings())

    with TestClient(app) as client:
        token = _dev_token(client)
        execution_id = _create_sleep_execution(client, token, seconds=1)

        with client.websocket_connect(
            f"/ws/executions/{execution_id}/logs?token={token}",
        ) as ws:
            publish_execution_log(
                uuid.UUID(execution_id),
                {
                    "type": "log",
                    "message": "test-line",
                    "step_id": "wait",
                },
            )

            for _ in range(30):
                msg = ws.receive_json()

                if msg.get("type") == "log" and msg.get("message") == "test-line":
                    break

            ws.close()


def test_websocket_streams_step_execution_logs(celery_eager):
    app = create_app(_test_settings())

    with TestClient(app) as client:
        token = _dev_token(client)
        execution_id = _create_sleep_execution(client, token, seconds=2)

        with client.websocket_connect(
            f"/ws/executions/{execution_id}/logs?token={token}",
        ) as ws:
            client.post(
                f"/executions/{execution_id}/run",
                headers=_auth(token),
            )

            saw_sleep = False
            saw_success = False

            for _ in range(30):
                msg = ws.receive_json()

                if msg.get("type") == "log" and "Sleeping" in msg.get("message", ""):
                    saw_sleep = True

                if msg.get("type") == "status" and msg.get("status") == "success":
                    saw_success = True

                if saw_sleep and saw_success:
                    break

            assert saw_sleep
            assert saw_success

            ws.close()


def test_execution_log_channel_format():
    eid = uuid.uuid4()
    channel = execution_log_channel(eid)

    assert channel.startswith("flowforge:logs:execution:")
