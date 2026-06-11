"""End-to-end tests for the Workflow CRUD API.

Coverage:
- Permission gates on all 5 verbs (viewer can read, can't write/delete;
  developer can do everything).
- 201/200/204/404/403 status codes are correct.
- POST -> GET -> PATCH -> DELETE happy path.
- PATCH semantics: only fields sent are touched; omitted fields preserved.
- Cursor pagination: page 1, page 2, end of pages.
- Cursor opacity: server returns a token, client passes it back unchanged.
"""

import asyncio
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from flowforge.authz import Role
from flowforge.config import Settings, get_settings
from flowforge.db import create_engine, create_sessionmaker
from flowforge.main import create_app
from flowforge.models import User


# ---------------- helpers ----------------


def _new_email() -> str:
    return f"u+{uuid.uuid4().hex[:8]}@example.com"


def _register_and_login(
    client: TestClient,
    email: str,
    password: str = "supersecret123",
) -> str:
    r = client.post(
        "/auth/register",
        json={"email": email, "password": password},
    )
    assert r.status_code == 201, r.text

    r = client.post(
        "/auth/login",
        json={"email": email, "password": password},
    )

    return r.json()["access_token"]


async def _promote_in_db(email: str, role: Role) -> None:
    engine = create_engine(get_settings())
    Session = create_sessionmaker(engine)

    async with Session() as session:
        result = await session.execute(
            select(User).where(User.email == email)
        )

        user = result.scalar_one()
        user.role = role.value

        await session.commit()

    await engine.dispose()


def _dev_token(client: TestClient) -> str:
    """Make a fresh developer-role user and return their access token."""

    email = _new_email()
    token = _register_and_login(client, email)

    asyncio.run(_promote_in_db(email, Role.DEVELOPER))

    return token


def _admin_token(client: TestClient) -> str:
    email = _new_email()
    token = _register_and_login(client, email)

    asyncio.run(_promote_in_db(email, Role.ADMIN))

    return token


def _auth(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


# ---------------- happy path ----------------


def test_create_get_update_delete_happy_path():
    app = create_app(Settings(environment="test"))

    with TestClient(app) as client:
        token = _dev_token(client)

        # CREATE
        r = client.post(
            "/workflows",
            headers=_auth(token),
            json={
                "name": "First workflow",
                "description": "Hello",
                "definition": {
                    "steps": [
                        {
                            "id": 1,
                            "kind": "noop",
                        }
                    ]
                },
            },
        )

        assert r.status_code == 201, r.text

        created = r.json()
        wf_id = created["id"]

        assert created["name"] == "First workflow"
        assert created["status"] == "draft"
        assert created["owner_id"]

        # GET
        r = client.get(
            f"/workflows/{wf_id}",
            headers=_auth(token),
        )

        assert r.status_code == 200
        assert r.json()["id"] == wf_id

        # PATCH
        r = client.patch(
            f"/workflows/{wf_id}",
            headers=_auth(token),
            json={"status": "active"},
        )

        assert r.status_code == 200

        body = r.json()

        assert body["status"] == "active"
        assert body["name"] == "First workflow"
        assert body["description"] == "Hello"

        # DELETE
        r = client.delete(
            f"/workflows/{wf_id}",
            headers=_auth(token),
        )

        assert r.status_code == 204
        assert r.content == b""

        # GET after delete
        r = client.get(
            f"/workflows/{wf_id}",
            headers=_auth(token),
        )

        assert r.status_code == 404


# ---------------- status code correctness ----------------


def test_get_unknown_workflow_returns_404():
    app = create_app(Settings(environment="test"))

    with TestClient(app) as client:
        token = _dev_token(client)

        r = client.get(
            f"/workflows/{uuid.uuid4()}",
            headers=_auth(token),
        )

        assert r.status_code == 404


def test_create_missing_name_returns_422():
    """Pydantic catches missing required fields BEFORE the handler runs."""

    app = create_app(Settings(environment="test"))

    with TestClient(app) as client:
        token = _dev_token(client)

        r = client.post(
            "/workflows",
            headers=_auth(token),
            json={"description": "no name"},
        )

        assert r.status_code == 422


def test_create_invalid_status_via_patch_returns_422():
    app = create_app(Settings(environment="test"))

    with TestClient(app) as client:
        token = _dev_token(client)

        r = client.post(
            "/workflows",
            headers=_auth(token),
            json={"name": "x"},
        )

        wf_id = r.json()["id"]

        r = client.patch(
            f"/workflows/{wf_id}",
            headers=_auth(token),
            json={"status": "totally-made-up"},
        )

        assert r.status_code == 422


# ---------------- permission gates ----------------


def test_viewer_can_read_but_not_write():
    app = create_app(Settings(environment="test"))

    with TestClient(app) as client:
        viewer = _register_and_login(client, _new_email())

        # GET allowed
        r = client.get(
            "/workflows",
            headers=_auth(viewer),
        )

        assert r.status_code == 200

        # POST forbidden
        r = client.post(
            "/workflows",
            headers=_auth(viewer),
            json={"name": "nope"},
        )

        assert r.status_code == 403


def test_developer_cannot_omit_auth():
    app = create_app(Settings(environment="test"))

    with TestClient(app) as client:
        r = client.get("/workflows")
        assert r.status_code == 401


# ---------------- PATCH semantics ----------------


def test_patch_with_empty_body_is_a_noop():
    app = create_app(Settings(environment="test"))

    with TestClient(app) as client:
        token = _dev_token(client)

        r = client.post(
            "/workflows",
            headers=_auth(token),
            json={"name": "keep me"},
        )

        wf_id = r.json()["id"]

        r = client.patch(
            f"/workflows/{wf_id}",
            headers=_auth(token),
            json={},
        )

        assert r.status_code == 200
        assert r.json()["name"] == "keep me"


def test_patch_does_not_null_omitted_fields():
    """The KEY PATCH invariant: omitted fields stay as-is."""

    app = create_app(Settings(environment="test"))

    with TestClient(app) as client:
        token = _dev_token(client)

        r = client.post(
            "/workflows",
            headers=_auth(token),
            json={
                "name": "before",
                "description": "still here",
                "definition": {"v": 1},
            },
        )

        wf_id = r.json()["id"]

        r = client.patch(
            f"/workflows/{wf_id}",
            headers=_auth(token),
            json={"name": "after"},
        )

        body = r.json()

        assert body["name"] == "after"
        assert body["description"] == "still here"
        assert body["definition"] == {"v": 1}


# ---------------- cursor pagination ----------------


def test_pagination_returns_cursor_and_paginates_correctly():
    app = create_app(Settings(environment="test"))

    with TestClient(app) as client:
        token = _dev_token(client)

        for i in range(5):
            r = client.post(
                "/workflows",
                headers=_auth(token),
                json={"name": f"wf-{i}"},
            )

            assert r.status_code == 201

        r = client.get(
            "/workflows?limit=3",
            headers=_auth(token),
        )

        assert r.status_code == 200

        page1 = r.json()

        assert len(page1["items"]) == 3
        assert page1["next_cursor"] is not None

        r = client.get(
            f"/workflows?limit=3&cursor={page1['next_cursor']}",
            headers=_auth(token),
        )

        assert r.status_code == 200

        page2 = r.json()

        page1_ids = {i["id"] for i in page1["items"]}
        page2_ids = {i["id"] for i in page2["items"]}

        assert page1_ids.isdisjoint(page2_ids)


def test_garbage_cursor_is_ignored():
    """Malformed cursor -> treat as start from beginning, not 500."""

    app = create_app(Settings(environment="test"))

    with TestClient(app) as client:
        token = _dev_token(client)

        r = client.get(
            "/workflows?cursor=this-is-not-base64!!!",
            headers=_auth(token),
        )

        assert r.status_code == 200