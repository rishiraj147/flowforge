"""Health-check endpoints."""

import redis.asyncio as aioredis

from fastapi import APIRouter, Depends


from flowforge.config import Settings, settings_from_request
from flowforge.db import get_session
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(
    settings: Settings = Depends(settings_from_request),
) -> dict[str, str]:
    """Liveness: is the process up? No external calls.

    Uses settings_from_request so the response reflects the Settings that were
    passed into create_app(...), not a globally cached singleton. This is what
    lets tests inject custom settings (e.g. environment="test") and see them
    actually take effect in the response.
    """
    
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.environment,
    }

@router.get("/health/db")
async def health_db(
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Readiness: can we actually reach Postgres?

    `Depends(get_session)` borrows a connection from the pool, runs a trivial
    query, then the dependency returns the connection to the pool. This is the
    smallest possible example of using a Session in a route.
    """

    await session.execute(text("SELECT 1"))
    return {"database": "ok"}


@router.get("/health/redis")
async def health_redis(
    settings: Settings = Depends(settings_from_request),
) -> dict[str, str]:
    """Readiness: can we reach Redis (Celery broker + result backend)?"""

    client = aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
    )

    try:
        pong = await client.ping()
    finally:
        await client.aclose()

    if not pong:
        raise RuntimeError("Redis ping failed")

    return {"redis": "ok"}