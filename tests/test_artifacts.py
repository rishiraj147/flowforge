"""Artifact storage tests (S3 mocked)."""

import asyncio
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from flowforge.authz import Role
from flowforge.config import Settings, get_settings
from flowforge.content_hash import artifact_storage_key, sha256_hex
from flowforge.db import create_engine, create_sessionmaker
from flowforge.main import create_app
from flowforge.models import User
from sqlalchemy import select


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


def _create_execution(client: TestClient, token: str) -> str:
    r = client.post(
        "/workflows",
        headers=_auth(token),
        json={
            "name": "artifact-test",
            "definition": {"steps": [{"id": "welcome", "kind": "noop"}]},
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
def client() -> TestClient:
    settings = Settings(environment="test", s3_enabled=True)

    with patch("flowforge.main.ensure_bucket"):
        app = create_app(settings)

        with TestClient(app) as test_client:
            yield test_client


def test_sha256_and_storage_key() -> None:
    data = b"hello artifact"
    digest = sha256_hex(data)

    assert len(digest) == 64
    assert artifact_storage_key(digest) == f"artifacts/{digest}"


@patch("flowforge.services.artifact_service.generate_presigned_download_url")
@patch("flowforge.services.artifact_service.upload_object")
@patch("flowforge.services.artifact_service.object_exists")
def test_upload_list_and_presign(
    mock_exists: object,
    mock_upload: object,
    mock_presign: object,
    client: TestClient,
) -> None:
    mock_exists.side_effect = [False, True]
    mock_presign.return_value = "https://minio.example/presigned"
    token = _dev_token(client)
    execution_id = _create_execution(client, token)
    body = b"report bytes"

    r = client.post(
        f"/executions/{execution_id}/artifacts",
        headers=_auth(token),
        files={"file": ("report.txt", body, "text/plain")},
    )

    assert r.status_code == 201, r.text
    payload = r.json()
    artifact = payload["artifact"]

    assert artifact["filename"] == "report.txt"
    assert artifact["size_bytes"] == len(body)
    assert artifact["content_hash"] == sha256_hex(body)
    assert artifact["deduplicated"] is False
    mock_upload.assert_called_once()

    r = client.post(
        f"/executions/{execution_id}/artifacts",
        headers=_auth(token),
        files={"file": ("report-copy.txt", body, "text/plain")},
    )

    assert r.status_code == 201, r.text
    assert r.json()["artifact"]["deduplicated"] is True
    mock_upload.assert_called_once()

    r = client.get(
        f"/executions/{execution_id}/artifacts",
        headers=_auth(token),
    )

    assert r.status_code == 200
    assert len(r.json()) == 2

    artifact_id = artifact["id"]

    r = client.get(
        f"/artifacts/{artifact_id}/download-url",
        headers=_auth(token),
    )

    assert r.status_code == 200
    assert r.json()["url"] == "https://minio.example/presigned"
    mock_presign.assert_called_once()
