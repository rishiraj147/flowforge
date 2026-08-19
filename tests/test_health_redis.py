"""Redis readiness test."""

from fastapi.testclient import TestClient

from flowforge.config import Settings
from flowforge.main import create_app


def test_health_redis_ok():
    app = create_app(Settings(environment="test"))

    with TestClient(app) as client:
        resp = client.get("/health/redis")

    assert resp.status_code == 200
    assert resp.json() == {"redis": "ok"}
