"""Exponential backoff + jitter — the math behind Celery autoretry.

Naive fixed-interval retry (every 30s for 100 workers) creates a *thundering herd*:
all failed tasks wake at the same instant and hammer a recovering API.

Exponential backoff spreads attempts: 30s → 60s → 120s → 240s (cap).
Jitter adds randomness so retries do not stay synchronized across workers.

Celery mirrors this via ``retry_backoff=30``, ``retry_backoff_max=240``,
``retry_jitter=True`` on the task decorator.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class BackoffSchedule:
    attempt: int
    base_seconds: float
    max_seconds: float
    delay_without_jitter: float
    delay_with_jitter: float
    formula: str


def exponential_delay_seconds(
    attempt: int,
    *,
    base_seconds: float = 30.0,
    max_seconds: float = 240.0,
) -> float:
    """Pure exponential backoff (no jitter).

    attempt 0 → min(30×2⁰, 240) = 30s
    attempt 1 → 60s
    attempt 2 → 120s
    attempt 3 → 240s
    attempt 4+ → 240s (capped)
    """

    if attempt < 0:
        attempt = 0

    return min(base_seconds * (2 ** attempt), max_seconds)


def jittered_delay_seconds(
    attempt: int,
    *,
    base_seconds: float = 30.0,
    max_seconds: float = 240.0,
    rng: random.Random | None = None,
) -> float:
    """Full jitter: uniform random in [0, exponential_delay].

    AWS and many systems recommend full jitter over equal jitter because it
    further desynchronizes workers after a shared outage.
    """

    ceiling = exponential_delay_seconds(
        attempt,
        base_seconds=base_seconds,
        max_seconds=max_seconds,
    )

    if ceiling <= 0:
        return 0.0

    generator = rng or random

    return generator.uniform(0, ceiling)


def describe_backoff(
    attempt: int,
    *,
    base_seconds: float = 30.0,
    max_seconds: float = 240.0,
    rng: random.Random | None = None,
) -> BackoffSchedule:
    """Human-readable schedule row for docs / API."""

    plain = exponential_delay_seconds(
        attempt,
        base_seconds=base_seconds,
        max_seconds=max_seconds,
    )
    jittered = jittered_delay_seconds(
        attempt,
        base_seconds=base_seconds,
        max_seconds=max_seconds,
        rng=rng,
    )

    return BackoffSchedule(
        attempt=attempt,
        base_seconds=base_seconds,
        max_seconds=max_seconds,
        delay_without_jitter=plain,
        delay_with_jitter=round(jittered, 3),
        formula=f"min({base_seconds} × 2^{attempt}, {max_seconds})",
    )
