"""Health-check endpoints."""

from fastapi import APIRouter, Depends

from flowforge.config import Settings, get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.environment,
    }