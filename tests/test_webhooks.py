"""Webhook API and delivery tests."""

import asyncio
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from flowforge.authz import Role
from flowforge.celery_app import celery_app
from flowforge.config import Settings, get_settings
from flowforge.db import create_engine, create_sessionmaker
from flowforge.main import create_app
from flowforge.models import User
from flowforge.webhook_hmac import compute_signature


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
            "name": "webhook-wf",
            "definition": {
                "steps": [
                    {"id": "A", "kind": "noop", "needs": []},
                ]
            },
        },
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


def test_create_webhook_returns_secret_and_url():
    app = create_app(Settings(environment="test"))

    with TestClient(app) as client:
        token = _dev_token(client)
        wf_id = _create_workflow(client, token)

        r = client.post(
            f"/workflows/{wf_id}/webhooks",
            headers=_auth(token),
            json={"enabled": True},
        )

    assert r.status_code == 201, r.text
    body = r.json()

    assert body["secret"]
    assert body["webhook"]["url_path"].startswith("/hooks/")
    assert body["webhook"]["workflow_id"] == wf_id


def test_webhook_delivery_requires_signature_and_idempotency_key():
    app = create_app(Settings(environment="test"))

    with TestClient(app) as client:
        token = _dev_token(client)
        wf_id = _create_workflow(client, token)

        created = client.post(
            f"/workflows/{wf_id}/webhooks",
            headers=_auth(token),
            json={"enabled": True},
        ).json()

        url_path = created["webhook"]["url_path"]
        secret = created["secret"]
        payload = b'{"event":"test"}'

        r = client.post(
            url_path,
            content=payload,
            headers={
                "X-FlowForge-Signature": compute_signature(secret, payload),
            },
        )

        assert r.status_code == 400

        r = client.post(
            url_path,
            content=payload,
            headers={"Idempotency-Key": "evt-1"},
        )

        assert r.status_code == 401


def test_webhook_delivery_triggers_execution(celery_eager):
    app = create_app(Settings(environment="test"))

    with TestClient(app) as client:
        token = _dev_token(client)
        wf_id = _create_workflow(client, token)

        created = client.post(
            f"/workflows/{wf_id}/webhooks",
            headers=_auth(token),
            json={"enabled": True},
        ).json()

        url_path = created["webhook"]["url_path"]
        secret = created["secret"]
        payload = json.dumps({"event": "order.created", "id": "ord_1"}).encode()
        headers = {
            "Idempotency-Key": "evt-ord-1",
            "X-FlowForge-Signature": compute_signature(secret, payload),
        }

        r = client.post(url_path, content=payload, headers=headers)

        assert r.status_code == 202
        body = r.json()

        assert body["triggered"] is True
        assert body["duplicate"] is False

        execution_id = body["execution_id"]

        r = client.get(
            f"/executions/{execution_id}",
            headers=_auth(token),
        )

        assert r.json()["trigger_source"] == "webhook"
        assert r.json()["status"] == "success"


def test_webhook_delivery_is_idempotent(celery_eager):
    app = create_app(Settings(environment="test"))

    with TestClient(app) as client:
        token = _dev_token(client)
        wf_id = _create_workflow(client, token)

        created = client.post(
            f"/workflows/{wf_id}/webhooks",
            headers=_auth(token),
            json={"enabled": True},
        ).json()

        url_path = created["webhook"]["url_path"]
        secret = created["secret"]
        payload = b'{"event":"dup"}'
        headers = {
            "Idempotency-Key": "same-key",
            "X-FlowForge-Signature": compute_signature(secret, payload),
        }

        r1 = client.post(url_path, content=payload, headers=headers)
        r2 = client.post(url_path, content=payload, headers=headers)

    assert r1.json()["triggered"] is True
    assert r2.json()["triggered"] is False
    assert r2.json()["duplicate"] is True
    assert r1.json()["execution_id"] == r2.json()["execution_id"]
