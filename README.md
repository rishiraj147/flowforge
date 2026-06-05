# FlowForge

FastAPI service scaffold.

## Stack

- **Poetry** — dependency management + virtualenv
- **Src/Layout** — import-safe package structure
- **FastAPI app factory** — `create_app()`
- **Pydantic Settings** — 12-factor config from env
- **docker-compose** — PostgreSQL 15 + Redis 7

## Quickstart

```bash
# 1. Install Poetry (once, per machine)
curl -sSL https://install.python-poetry.org | python3 -

# 2. Install deps into a managed virtualenv
poetry install

# 3. Local config
cp .env.example .env

# 4. Start backing services
docker compose up -d

# 5. Run the API
poetry run uvicorn flowforge.main:app --reload

# 6. Test
poetry run pytest
```

Visit:

http://localhost:8000/health

http://localhost:8000/docs
