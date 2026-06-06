"""Database wiring: engine, sessionmaker, and a FastAPI session dependency.

Three distinct objects, three distinct jobs:

Engine
    -> owns the connection POOL + knows how to talk to Postgres.
       Created ONCE per process. Expensive. Long-lived.

sessionmaker
    -> a FACTORY that stamps out Session objects with identical
       config. Created ONCE. Cheap to call. Not a session itself.

Session
    -> one short-lived "unit of work" / conversation with the DB,
       bound to ONE connection borrowed from the pool. Created PER
       REQUEST, then returned. Holds your in-flight objects + txn.
"""

from collections.abc import AsyncGenerator

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from flowforge.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    """Build the async engine (and its connection pool). Call once at startup."""
    return create_async_engine(
        settings.database_url,
        echo=settings.db_echo,  # log SQL - handy while learning
        pool_size=settings.db_pool_size,  # persistent connections kept open
        max_overflow=settings.db_max_overflow,  # temporary extras under load
        pool_pre_ping=True,  # check a conn is alive before using it
    )


def create_sessionmaker(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Build the session factory bound to the engine. Call once at startup."""
    return async_sessionmaker(
        bind=engine,
        # Keep attributes usable after commit() instead of expiring them,
        # so a handler can read obj.id after commit without triggering a query.
        expire_on_commit=False,
    )


async def get_session(
    request: Request,
) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yield one Session per request, always closed.

    Usage in a route:

        async def handler(
            session: AsyncSession = Depends(get_session)
        ):
            ...

    The sessionmaker lives on app.state (set in lifespan), so this dependency
    pulls the SAME factory the whole app shares.
    """

    factory: async_sessionmaker[AsyncSession] = (
        request.app.state.sessionmaker
    )

    async with factory() as session:
        # opens session, borrows a pooled connection
        yield session
        # on exit: session closes, connection returns to the pool