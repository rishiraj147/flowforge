"""Application factory.

`create_app()` builds and returns a configured FastAPI instance. Nothing at
import time creates a global app, which keeps construction explicit and
test-friendly.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from flowforge.api.health import router as health_router
from flowforge.config import Settings, get_settings
from flowforge.db import create_engine, create_sessionmaker


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: open shared resources (DB pool, Redis client) here and stash
    # them on app.state. Shutdown: close them after `yield`.

    settings: Settings = app.state.settings
    engine= create_engine(settings)
    app.state.engine = engine
    app.state.sessionmaker = create_sessionmaker(engine)

    # e.g.
    # app.state.redis = redis.asyncio.from_url(settings.redis_url)

    yield # app servers request here, reusing the shared pool/factory

    # shutdown: dispose the engine so all pooled connections close cleanly.
    await engine.dispose()

    # e.g.
    # await app.state.redis.aclose()


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

    # Mount routers. Add new feature routers here as the app grows.
    app.include_router(health_router)

    return app


# A module-level instance ONLY for the
# `uvicorn flowforge.main:app` convenience.
# It is created by calling the factory, so there is one construction path.
app = create_app()