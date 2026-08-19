# FlowForge load testing (Locust)

## 1. Prerequisites

- `docker compose up -d` (postgres, redis)
- API: `poetry run uvicorn flowforge.main:app --reload`
- **Celery worker** (required for executions to finish):
  `poetry run celery -A flowforge.celery_app worker --loglevel=info`
- Optional: Grafana/Prometheus for side-by-side metrics

## 2. Install Locust

```bash
poetry install
```

## 3. Auth for load tests (pick one)

### Option A — Shared account (recommended first run)

One developer login is shared by **all** Locust virtual users. Ten users in the UI does **not** mean ten DB users.

```bash
# Register once, promote once:
docker compose exec postgres psql -U flowforge -d flowforge \
  -c "UPDATE users SET role='developer' WHERE email='loadtest@example.com';"

export FLOWFORGE_LOAD_TEST_EMAIL=loadtest@example.com
export FLOWFORGE_LOAD_TEST_PASSWORD=supersecret123
```

### Option B — Auto-register (unique user per virtual user)

Add to your API `.env` (local only — never in production):

```
FLOWFORGE_LOAD_TEST_AUTO_DEVELOPER_ROLE=true
```

Restart uvicorn, then:

```bash
export FLOWFORGE_LOAD_TEST_MODE=auto
export FLOWFORGE_LOAD_TEST_PASSWORD=supersecret123
```

Each Locust user registers `locust-<uuid>@loadtest.example.com` on start.

## 4. Start Locust

```bash
poetry run locust -f load_tests/locustfile.py --host http://localhost:8000
```

Open **http://localhost:8089**

## 5. First run (start small)

| Setting | Value |
|---------|--------|
| Number of users | **3** |
| Spawn rate | **1** |
| Host | `http://localhost:8000` |

Click **Start swarming**. Watch **Statistics** and **Charts**.

## 6. What each Locust column means

- **RPS** — requests per second (throughput)
- **Failures** — HTTP errors or marked failures (login, timeout waiting for success)
- **Average / 95%ile** — latency; focus on **95%ile** for `/executions/[id]/run` and poll lines

## 7. Ramp up gradually

Increase users: 3 → 5 → 10 → 20. Note when 95%ile jumps or failures appear.

Pair with Grafana: `task_duration_seconds`, `workflows_triggered_total`, HTTP RED panels.

## 8. Headless run (optional)

```bash
poetry run locust -f load_tests/locustfile.py \
  --host http://localhost:8000 \
  --headless -u 5 -r 1 -t 5m \
  --html load_tests/report.html
```
