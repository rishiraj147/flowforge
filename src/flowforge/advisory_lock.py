"""PostgreSQL advisory locks for multi-instance leader election / idempotent triggers.

With N API servers each running APScheduler, the same cron job fires on every
instance. Advisory locks ensure only one process triggers a given schedule slot.

Uses pg_try_advisory_xact_lock — released automatically when the transaction ends.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Namespace for schedule-trigger locks (arbitrary stable int4).
SCHEDULE_LOCK_NAMESPACE = 75301

# Global scheduler leader lock (single int8) — optional scan coordination.
SCHEDULER_LEADER_LOCK_KEY = 0xFF4F4F01


def schedule_lock_pair(schedule_id: uuid.UUID) -> tuple[int, int]:
    """Two-int advisory lock key for a schedule row."""

    token = schedule_id.int % (2**31 - 1)

    return (SCHEDULE_LOCK_NAMESPACE, token)


async def try_advisory_xact_lock(session: AsyncSession, key1: int, key2: int) -> bool:
    result = await session.execute(
        text("SELECT pg_try_advisory_xact_lock(:key1, :key2)"),
        {"key1": key1, "key2": key2},
    )

    return bool(result.scalar_one())


async def try_scheduler_leader_lock(session: AsyncSession) -> bool:
    result = await session.execute(
        text("SELECT pg_try_advisory_xact_lock(:key)"),
        {"key": SCHEDULER_LEADER_LOCK_KEY},
    )

    return bool(result.scalar_one())
