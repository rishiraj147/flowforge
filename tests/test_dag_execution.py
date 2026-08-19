"""Full DAG execution tests (Step 2.6)."""

import asyncio
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


DAG_DEFINITION = {
    "steps": [
        {"id": "A", "kind": "noop", "needs": []},
        {"id": "B", "kind": "noop", "needs": ["A"]},
        {"id": "C", "kind": "noop", "needs": ["B"]},
        {"id": "D", "kind": "noop", "needs": ["B"]},
    ]
}


@pytest.fixture
def celery_eager():
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True

    yield

    celery_app.conf.task_always_eager = False
    celery_app.conf.task_eager_propagates = False


def test_full_dag_run_completes_all_steps(celery_eager):
    """A → B → (C, D parallel) runs to completion via POST /executions/{id}/run."""

    app = create_app(Settings(environment="test"))

    with TestClient(app) as client:
        token = _dev_token(client)

        r = client.post(
            "/workflows",
            headers=_auth(token),
            json={"name": "dag-test", "definition": DAG_DEFINITION},
        )

        assert r.status_code == 201

        wf_id = r.json()["id"]

        r = client.post(
            f"/workflows/{wf_id}/executions",
            headers=_auth(token),
        )

        assert r.status_code == 201

        execution_id = r.json()["id"]
        assert r.json()["status"] == "pending"

        r = client.post(
            f"/executions/{execution_id}/run",
            headers=_auth(token),
        )

        assert r.status_code == 202
        assert r.json()["status"] == "success"

        r = client.get(
            f"/executions/{execution_id}/task-runs",
            headers=_auth(token),
        )

        assert r.status_code == 200

        task_runs = r.json()

        assert len(task_runs) == 4

        by_step = {tr["step_id"]: tr["status"] for tr in task_runs}

        assert by_step == {
            "A": "success",
            "B": "success",
            "C": "success",
            "D": "success",
        }

        r = client.get(
            f"/executions/{execution_id}",
            headers=_auth(token),
        )

        assert r.json()["status"] == "success"
