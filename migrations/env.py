"""Alembic environment, wired for SQLAlchemy 2.0 async.

Key ideas:
- We import Base.metadata as 'target_metadata'. Autogenerate diffs THIS against
  the live database to decide what changed.
- We inject the DB URL from app Settings, so migrations hit the same DB the app
  uses (no duplicated connection string).
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from flowforge.config import get_settings
from flowforge.models import Base  # noqa: F401 (imports all models -> metadata)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Single source of truth for the URL: pull from Settings, not alembic.ini.
config.set_main_option(
    "sqlalchemy.url",
    get_settings().database_url,
)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to a script without a live DB connection ('alembic upgrade --sql')."""

    url = config.get_main_option("sqlalchemy.url")

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,  # detect column TYPE changes, not just add/drop
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations against a live DB using an async engine."""

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # migrations are one-shot; no pool needed
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())