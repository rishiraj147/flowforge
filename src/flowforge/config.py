"""Application configuration via Pydantic Settings (12-factor: config from env)."""

from functools import lru_cache
from fastapi import Request

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

    # --- connection pool tuning (see WHY: pooling) --- 
    db_echo: bool =False            # log every SQL statement (turn on to learn)
    db_pool_size: int = 5           # persistent connections to kept open per process
    db_max_overflow: int = 10       # extra short-lived connections under burst

    # --- auth / JWT ---
    # secret used to sign JWTs. In production, this MUST be set to a long random string.
    # If you change this, all existing JWTs will be invalidated (users will have to log in again).
    jwt_secret_key: str= "change-me-in-production-to-a-long-random-string"
    jwt_algorithm: str = "HS256"  # HMAC + SHA-256, symmetric algorithm used to sign JWTs
    access_token_ttl_minutes: int = 15 # short - limits damage if stolen
    refresh_token_ttl_days: int = 7 # long - allows users to stay logged in for a week


    


@lru_cache
def get_settings() -> Settings:
    """
    Return a cached Settings instance.

    lru_cache makes this a singleton: env is parsed once,
    and FastAPI can use this function directly as a dependency
    (Depends(get_settings)).
    """
    return Settings()

def settings_from_request(request:Request) -> Settings:
    """FastAPI dependency: return the Settings instance attached to THIS app.

    Why this exists (vs. just using get_settings):
    - create_app(settings) stores the caller's Settings on app.state.settings.
    - Tests build apps with custom Settings, e.g.
      create_app(Settings(environment="test")).
    - get_settings() ignores all that and returns a globally cached no-arg
      Settings, so handlers using Depends(get_settings) would never see the
      test's overrides.
    - This dependency reads from app.state, so whatever was passed to
      create_app is exactly what the handler sees. Per-app, not global.
    """

    return request.app.state.settings