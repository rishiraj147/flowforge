"""Application factory.

`create_app()` builds and returns a configured FastAPI instance. Nothing at
import time creates a global app, which keeps construction explicit and
test-friendly.
"""

from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI

from flowforge.api.health import router as health_router
from flowforge.config import Settings, get_settings
from flowforge.db import create_engine, create_sessionmaker
from flowforge.api.auth import router as auth_router
from flowforge.api.workflows import router as workflows_router
from flowforge.api.users import router as users_router
from flowforge.api.demo import router as demo_router
from flowforge.api.executions import router as executions_router
from flowforge.api.schedules import router as schedules_router
from flowforge.api.webhooks import router as webhooks_router
from flowforge.api.hooks import router as hooks_router
from flowforge.api.log_stream import router as log_stream_router
from flowforge.api.artifacts import router as artifacts_router
from flowforge.api.dead_letter import router as dead_letter_router
from flowforge.prometheus_setup import setup_prometheus
from flowforge.scheduler import WorkflowCronScheduler
from flowforge.s3_client import ensure_bucket


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: open shared resources (DB pool, Redis client) here and stash
    # them on app.state. Shutdown: close them after `yield`.

    settings: Settings = app.state.settings
    engine = create_engine(settings)
    app.state.engine = engine
    app.state.sessionmaker = create_sessionmaker(engine)

    app.state.redis = aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
    )

    scheduler = WorkflowCronScheduler(app.state.sessionmaker, settings)
    app.state.scheduler = scheduler
    await scheduler.start()

    if settings.s3_enabled:
        ensure_bucket(settings)

    yield  # app serves requests here, reusing the shared pool/factory

    scheduler.shutdown()

    await app.state.redis.aclose()

    # shutdown: dispose the engine so all pooled connections close cleanly.
    await engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a FastAPI app.

    Pass `settings` to override config (e.g. in tests).
    """

    settings = settings or get_settings()

    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        lifespan=lifespan,
    )

    app.state.settings = settings

    setup_prometheus(app, settings)

    # Mount routers. Add new feature routers here as the app grows.
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(users_router)
    app.include_router(workflows_router)
    app.include_router(demo_router)
    app.include_router(executions_router)
    app.include_router(schedules_router)
    app.include_router(webhooks_router)
    app.include_router(hooks_router)
    app.include_router(log_stream_router)
    app.include_router(artifacts_router)
    app.include_router(dead_letter_router)

    return app


# A module-level instance ONLY for the
# `uvicorn flowforge.main:app` convenience.
# It is created by calling the factory, so there is one construction path.
app = create_app()