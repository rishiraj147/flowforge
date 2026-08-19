"""End-to-end RBAC tests.

Coverage goals:
- Default role on registration is viewer.
- Viewer is blocked from admin endpoints (403).
- Admin can access admin endpoints (200).
- Admin can promote / demote another user.
- 404 when promoting a missing user.
- Self-promotion via /auth/register is impossible (no `role` field accepted).
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
    """Bypass HTTP and set a user's role directly in Postgres.

    Real apps need this for the FIRST admin (chicken-and-egg: only an admin can
    promote, but there's no admin yet). In production we'd do it via a CLI or a
    one-shot SQL UPDATE the first time the system is deployed.
    """

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


# ---------------- tests ----------------

def test_new_user_defaults_to_viewer():
    app = create_app(Settings(environment="test"))
    email = _new_email()

    with TestClient(app) as client:
        token = _register_and_login(client, email)

        r = client.get(
            "/users/me",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert r.status_code == 200
        assert r.json()["role"] == "viewer"


def test_load_test_auto_developer_role_flag():
    """Local load-test flag only — not available to clients via the register body."""

    app = create_app(
        Settings(environment="test", load_test_auto_developer_role=True),
    )
    email = _new_email()

    with TestClient(app) as client:
        r = client.post(
            "/auth/register",
            json={"email": email, "password": "supersecret123"},
        )

        assert r.status_code == 201
        assert r.json()["role"] == "developer"


def test_register_payload_cannot_set_role():
    """Even if the client sends `role: admin`, it must be ignored by UserCreate."""

    app = create_app(Settings(environment="test"))
    email = _new_email()

    with TestClient(app) as client:
        # extra `role` field — UserCreate has no such field, Pydantic drops it.
        r = client.post(
            "/auth/register",
            json={
                "email": email,
                "password": "supersecret123",
                "role": "admin",
            },
        )

        assert r.status_code == 201

        # confirm the actual stored role is the safe default
        r = client.post(
            "/auth/login",
            json={
                "email": email,
                "password": "supersecret123",
            },
        )

        their_token = r.json()["access_token"]

        r = client.get(
            "/users/me",
            headers={"Authorization": f"Bearer {their_token}"},
        )

        assert r.json()["role"] == "viewer"


def test_viewer_forbidden_from_listing_users():
    app = create_app(Settings(environment="test"))
    email = _new_email()

    with TestClient(app) as client:
        token = _register_and_login(client, email)

        r = client.get(
            "/users",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert r.status_code == 403
        assert "users:manage" in r.json()["detail"]


def test_admin_can_list_users():
    app = create_app(Settings(environment="test"))
    admin_email = _new_email()

    with TestClient(app) as client:
        token = _register_and_login(client, admin_email)

        asyncio.run(
            _promote_in_db(admin_email, Role.ADMIN)
        )

        # No re-login needed: role is read fresh from DB on every request,
        # so the existing token now sees the new role.
        r = client.get(
            "/users",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert r.status_code == 200

        body = r.json()
        assert isinstance(body, list)
        assert any(
            u["email"] == admin_email
            for u in body
        )


def test_admin_can_promote_another_user():
    app = create_app(Settings(environment="test"))

    admin_email = _new_email()
    target_email = _new_email()

    with TestClient(app) as client:
        admin_token = _register_and_login(client, admin_email)
        target_token = _register_and_login(client, target_email)

        asyncio.run(
            _promote_in_db(admin_email, Role.ADMIN)
        )

        # find target id via their own /me
        r = client.get(
            "/users/me",
            headers={"Authorization": f"Bearer {target_token}"},
        )

        target_id = r.json()["id"]

        # admin promotes target -> developer
        r = client.patch(
            f"/users/{target_id}/role",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"role": "developer"},
        )

        assert r.status_code == 200
        assert r.json()["role"] == "developer"


def test_developer_cannot_promote_users():
    app = create_app(Settings(environment="test"))
    dev_email = _new_email()

    with TestClient(app) as client:
        dev_token = _register_and_login(client, dev_email)

        asyncio.run(
            _promote_in_db(dev_email, Role.DEVELOPER)
        )

        # any user_id will do — we should fail at the authz wall before touching DB
        r = client.patch(
            f"/users/{uuid.uuid4()}/role",
            headers={"Authorization": f"Bearer {dev_token}"},
            json={"role": "admin"},
        )

        assert r.status_code == 403


def test_promote_unknown_user_returns_404():
    app = create_app(Settings(environment="test"))
    admin_email = _new_email()

    with TestClient(app) as client:
        admin_token = _register_and_login(client, admin_email)

        asyncio.run(
            _promote_in_db(admin_email, Role.ADMIN)
        )

        r = client.patch(
            f"/users/{uuid.uuid4()}/role",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"role": "developer"},
        )

        assert r.status_code == 404


def test_invalid_role_value_returns_422():
    """Pydantic's Literal validation rejects bad roles BEFORE the handler runs."""

    app = create_app(Settings(environment="test"))
    admin_email = _new_email()

    with TestClient(app) as client:
        admin_token = _register_and_login(client, admin_email)

        asyncio.run(
            _promote_in_db(admin_email, Role.ADMIN)
        )

        r = client.patch(
            f"/users/{uuid.uuid4()}/role",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"role": "superadmin"},  # not in Literal
        )

        # 422 Unprocessable Entity = "your JSON parsed but failed validation"
        assert r.status_code == 422