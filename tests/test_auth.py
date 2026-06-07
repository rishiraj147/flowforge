"""End-to-end auth tests through TestClient.

These exercise the whole stack: HTTP -> router -> service -> DB -> JWT -> header parsing.
Each test uses a UNIQUE EMAIL so reruns don't collide with the UNIQUE constraint
(simple isolation pattern; we'll graduate to per-test rollback later).
"""

import uuid

from fastapi.testclient import TestClient

from flowforge.config import Settings
from flowforge.main import create_app


def _new_email() -> str:
    return f"alice+{uuid.uuid4().hex[:8]}@example.com"


def test_register_login_me_and_refresh():
    """The full happy path in one test — read it as a story."""

    app = create_app(Settings(environment="test"))
    email = _new_email()
    password = "supersecret123"

    with TestClient(app) as client:
        # --- 1. Register ---
        r = client.post(
            "/auth/register",
            json={
                "email": email,
                "password": password,
                "full_name": "Alice",
            },
        )

        assert r.status_code == 201, r.text

        body = r.json()
        assert body["email"] == email

        # CRITICAL invariant: password / hash MUST NOT leak.
        assert "password" not in body
        assert "password_hash" not in body

        # --- 2. Login ---
        r = client.post(
            "/auth/login",
            json={
                "email": email,
                "password": password,
            },
        )

        assert r.status_code == 200, r.text

        tokens = r.json()
        access = tokens["access_token"]
        refresh = tokens["refresh_token"]

        assert access and refresh and access != refresh

        # --- 3. Call protected /users/me with the access token ---
        r = client.get(
            "/users/me",
            headers={"Authorization": f"Bearer {access}"},
        )

        assert r.status_code == 200, r.text

        me = r.json()
        assert me["email"] == email
        assert me["full_name"] == "Alice"

        # --- 4. Use the refresh token to get a new access token ---
        r = client.post(
            "/auth/refresh",
            json={"refresh_token": refresh},
        )

        assert r.status_code == 200, r.text

        new_access = r.json()["access_token"]
        assert new_access  # we got a token

        # --- 5. The new access token also works on protected routes ---
        r = client.get(
            "/users/me",
            headers={"Authorization": f"Bearer {new_access}"},
        )

        assert r.status_code == 200
        assert r.json()["email"] == email


def test_register_duplicate_email_returns_409():
    app = create_app(Settings(environment="test"))
    email = _new_email()

    with TestClient(app) as client:
        client.post(
            "/auth/register",
            json={
                "email": email,
                "password": "supersecret123",
            },
        )

        # second register with same email -> conflict
        r = client.post(
            "/auth/register",
            json={
                "email": email,
                "password": "anotherpassword456",
            },
        )

        assert r.status_code == 409


def test_login_with_wrong_password_returns_401():
    app = create_app(Settings(environment="test"))
    email = _new_email()

    with TestClient(app) as client:
        client.post(
            "/auth/register",
            json={
                "email": email,
                "password": "supersecret123",
            },
        )

        r = client.post(
            "/auth/login",
            json={
                "email": email,
                "password": "WRONG",
            },
        )

        assert r.status_code == 401

        # Generic message — must NOT reveal whether email or password was wrong.
        assert r.json()["detail"] == "Invalid credentials"


def test_login_with_unknown_email_returns_401():
    app = create_app(Settings(environment="test"))

    with TestClient(app) as client:
        r = client.post(
            "/auth/login",
            json={
                "email": _new_email(),
                "password": "supersecret123",
            },
        )

        assert r.status_code == 401
        assert r.json()["detail"] == "Invalid credentials"


def test_me_without_token_returns_401():
    app = create_app(Settings(environment="test"))

    with TestClient(app) as client:
        r = client.get("/users/me")

        assert r.status_code == 401


def test_me_with_garbage_token_returns_401():
    app = create_app(Settings(environment="test"))

    with TestClient(app) as client:
        r = client.get(
            "/users/me",
            headers={"Authorization": "Bearer not-a-real-jwt"},
        )

        assert r.status_code == 401


def test_me_rejects_refresh_token_in_authorization_header():
    """Using a refresh token where an access token is expected must fail.

    This is exactly why we embed "type" in the payload.
    """

    app = create_app(Settings(environment="test"))
    email = _new_email()

    with TestClient(app) as client:
        client.post(
            "/auth/register",
            json={
                "email": email,
                "password": "supersecret123",
            },
        )

        r = client.post(
            "/auth/login",
            json={
                "email": email,
                "password": "supersecret123",
            },
        )

        refresh = r.json()["refresh_token"]

        r = client.get(
            "/users/me",
            headers={"Authorization": f"Bearer {refresh}"},
        )

        assert r.status_code == 401


def test_refresh_rejects_access_token():
    """And the reverse — access tokens are not refresh tokens."""

    app = create_app(Settings(environment="test"))
    email = _new_email()

    with TestClient(app) as client:
        client.post(
            "/auth/register",
            json={
                "email": email,
                "password": "supersecret123",
            },
        )

        r = client.post(
            "/auth/login",
            json={
                "email": email,
                "password": "supersecret123",
            },
        )

        access = r.json()["access_token"]

        r = client.post(
            "/auth/refresh",
            json={"refresh_token": access},
        )

        assert r.status_code == 401