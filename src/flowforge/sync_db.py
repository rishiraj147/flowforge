"""Synchronous database access for Celery workers.

FastAPI uses async SQLAlchemy; Celery tasks run in sync worker processes.
This module converts the async Postgres URL to a sync psycopg URL and exposes
a session factory for task bodies and signal handlers.
"""

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from flowforge.config import get_settings


def sync_database_url(async_url: str) -> str:
    """Map postgresql+asyncpg://... to postgresql+psycopg://..."""

    if async_url.startswith("postgresql+asyncpg://"):
        return "postgresql+psycopg://" + async_url.split("postgresql+asyncpg://", 1)[1]

    return async_url


@lru_cache
def get_sync_engine() -> Engine:
    settings = get_settings()

    return create_engine(
        sync_database_url(settings.database_url),
        pool_pre_ping=True,
    )


@lru_cache
def get_sync_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(
        bind=get_sync_engine(),
        expire_on_commit=False,
    )


def sync_session() -> Session:
    """Open a sync session (caller must close/commit)."""

    return get_sync_sessionmaker()()
