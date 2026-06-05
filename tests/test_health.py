"""Health endpoints test - note how the factory makes this trivial."""

from fastapi.testclient import TestClient
from flowforge.config import Settings
from flowforge.main import create_app

def test_health_ok():
    # Build an isolated app with test-specific settings. No global state,
    # no .env dependence, no shared mutable app between tests.

    app=create_app(Settings(environment="test", app_name="FlowForge-Test"))
    client = TestClient(app)

    response = client.get("/health")
    assert response.status_code == 200
    body= response.json()
    assert body["status"] == "ok"
    assert body["app"] == "FlowForge-Test"
    assert body["environment"] == "test"