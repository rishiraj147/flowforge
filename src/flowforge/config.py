"""Application configuration via Pydantic Settings (12-factor: config from env)."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # model_config tells pydantic-settings to read a local .env file in dev,
    # but real environment variables always win over the file (12-factor).
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="FLOWFORGE_",  # e.g. FLOWFORGE_DEBUG, FLOWFORGE_DATABASE_URL
        extra="ignore",
    )

    # --- app
    app_name: str = "FlowForge"
    debug: bool = False
    environment: str = "local"  # local | staging | production

    # --- backing services (URLs, not host/port/user split - 12-factor IV)
    database_url: str = Field(
        default="postgresql+asyncpg://flowforge:flowforge@localhost:5432/flowforge"
    )

    redis_url: str = Field(
        default="redis://localhost:6379/0"
    )


@lru_cache
def get_settings() -> Settings:
    """
    Return a cached Settings instance.

    lru_cache makes this a singleton: env is parsed once,
    and FastAPI can use this function directly as a dependency
    (Depends(get_settings)).
    """
    return Settings()