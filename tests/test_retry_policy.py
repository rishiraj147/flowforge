"""Retry backoff math tests."""

from flowforge.retry_policy import (
    describe_backoff,
    exponential_delay_seconds,
    jittered_delay_seconds,
)


def test_exponential_backoff_schedule():
    assert exponential_delay_seconds(0) == 30
    assert exponential_delay_seconds(1) == 60
    assert exponential_delay_seconds(2) == 120
    assert exponential_delay_seconds(3) == 240
    assert exponential_delay_seconds(4) == 240


def test_jitter_stays_within_ceiling():
    attempt = 2
    ceiling = exponential_delay_seconds(attempt)

    for _ in range(20):
        delay = jittered_delay_seconds(attempt, rng=None)

        assert 0 <= delay <= ceiling


def test_describe_backoff_formula():
    row = describe_backoff(2, rng=None)

    assert row.formula == "min(30.0 × 2^2, 240.0)"
    assert row.delay_without_jitter == 120.0
