"""Readiness test - /health/db should succeed if Postgres is reachable and properly configured."""

from fastapi.testclient import TestClient

from flowforge.config import Settings
from flowforge.main import create_app

def test_health_db_ok():
    #  Uses the default settings, -> connects to local postgress in Docker

    app=create_app(Settings(environment="test"))

    with TestClient(app) as client:
        resp=client.get("/health/db")

    assert resp.status_code == 200
    assert resp.json() == {"database": "ok"}
