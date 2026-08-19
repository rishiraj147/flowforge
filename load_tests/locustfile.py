"""FlowForge load tests (Locust) — Phase 5 scope.

Run the API + Celery worker before starting Locust.

Environment — pick one auth mode:

  Shared account (default, simplest):
    FLOWFORGE_LOAD_TEST_EMAIL     one developer user
    FLOWFORGE_LOAD_TEST_PASSWORD  password
    All Locust virtual users share this login — you do NOT need N accounts for N users.

  Auto-register (unique user per virtual user):
    FLOWFORGE_LOAD_TEST_MODE=auto
    FLOWFORGE_LOAD_TEST_PASSWORD=supersecret123
    FLOWFORGE_LOAD_TEST_AUTO_DEVELOPER_ROLE=true   # in API .env (local only)

Optional:
  FLOWFORGE_HOST                default http://localhost:8000

Example:
  export FLOWFORGE_LOAD_TEST_EMAIL=loadtest@example.com
  export FLOWFORGE_LOAD_TEST_PASSWORD=supersecret123
  poetry run locust -f load_tests/locustfile.py --host http://localhost:8000

Open http://localhost:8089 — start with 3 users, spawn rate 1, watch Statistics + Charts.
"""

from __future__ import annotations

import os
import time
import uuid

from locust import HttpUser, between, events, task

NOOP_DEFINITION = {
    "steps": [
        {"id": "run", "kind": "noop"},
    ],
}


class FlowForgeUser(HttpUser):
    """Simulates a developer running noop workflow executions."""

    wait_time = between(1, 3)

    token: str | None = None
    workflow_id: str | None = None

    def on_start(self) -> None:
        password = os.environ.get("FLOWFORGE_LOAD_TEST_PASSWORD", "").strip()
        mode = os.environ.get("FLOWFORGE_LOAD_TEST_MODE", "shared").strip().lower()

        if not password:
            raise RuntimeError(
                "Set FLOWFORGE_LOAD_TEST_PASSWORD (see load_tests/README.md)"
            )

        if mode == "auto":
            email = f"locust-{uuid.uuid4().hex}@loadtest.example.com"
            with self.client.post(
                "/auth/register",
                json={"email": email, "password": password},
                name="/auth/register",
                catch_response=True,
            ) as response:
                if response.status_code != 201:
                    response.failure(
                        f"register failed: {response.status_code} {response.text}"
                    )
                    return
        else:
            email = os.environ.get("FLOWFORGE_LOAD_TEST_EMAIL", "").strip()
            if not email:
                raise RuntimeError(
                    "Shared mode: set FLOWFORGE_LOAD_TEST_EMAIL and "
                    "FLOWFORGE_LOAD_TEST_PASSWORD"
                )

        with self.client.post(
            "/auth/login",
            json={"email": email, "password": password},
            name="/auth/login",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"login failed: {response.status_code} {response.text}")
                return

            self.token = response.json()["access_token"]

        headers = self._auth_headers()

        with self.client.post(
            "/workflows",
            headers=headers,
            json={"name": f"locust-{uuid.uuid4().hex[:8]}", "definition": NOOP_DEFINITION},
            name="/workflows [create]",
            catch_response=True,
        ) as response:
            if response.status_code != 201:
                response.failure(f"create workflow failed: {response.status_code}")
                return

            self.workflow_id = response.json()["id"]

    def _auth_headers(self) -> dict[str, str]:
        if self.token is None:
            return {}

        return {"Authorization": f"Bearer {self.token}"}

    @task(1)
    def health(self) -> None:
        self.client.get("/health", name="/health")

    @task(5)
    def run_noop_execution(self) -> None:
        if self.token is None or self.workflow_id is None:
            return

        headers = self._auth_headers()
        e2e_start = time.time()

        with self.client.post(
            f"/workflows/{self.workflow_id}/executions",
            headers=headers,
            name="/workflows/[id]/executions [create]",
            catch_response=True,
        ) as response:
            if response.status_code != 201:
                response.failure(f"create execution: {response.status_code}")
                return

            execution_id = response.json()["id"]

        with self.client.post(
            f"/executions/{execution_id}/run",
            headers=headers,
            name="/executions/[id]/run",
            catch_response=True,
        ) as response:
            if response.status_code != 202:
                response.failure(f"run execution: {response.status_code}")
                return

        finished_ok = self._poll_execution(execution_id, headers)
        e2e_ms = (time.time() - e2e_start) * 1000

        if finished_ok:
            events.request.fire(
                request_type="E2E",
                name="noop execution (create→run→success)",
                response_time=e2e_ms,
                response_length=0,
                exception=None,
                context={},
            )
        else:
            events.request.fire(
                request_type="E2E",
                name="noop execution (create→run→success)",
                response_time=e2e_ms,
                response_length=0,
                exception=TimeoutError("execution did not succeed within timeout"),
                context={},
            )

    def _poll_execution(self, execution_id: str, headers: dict[str, str]) -> bool:
        deadline = time.time() + 120

        while time.time() < deadline:
            with self.client.get(
                f"/executions/{execution_id}",
                headers=headers,
                name="/executions/[id] [poll]",
                catch_response=True,
            ) as response:
                if response.status_code != 200:
                    return False

                status = response.json().get("status")

                if status == "success":
                    return True

                if status == "failed":
                    return False

            time.sleep(0.5)

        return False
