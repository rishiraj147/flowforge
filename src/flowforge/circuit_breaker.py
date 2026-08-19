"""Redis-backed circuit breaker — stop hammering a failing dependency.

Electrical analogy: when current surges, the breaker *opens* and stops flow.
After a cooldown it enters *half-open* (one probe allowed). Success *closes*
the circuit; failure re-opens it.

Used by ``http`` steps so workers do not retry into a dead API.
"""

from __future__ import annotations

import time
from enum import Enum
from functools import lru_cache

import redis

from flowforge.config import get_settings
from flowforge.exceptions import CircuitOpenError, PermanentStepError, TransientStepError


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@lru_cache
def get_sync_redis() -> redis.Redis:
    settings = get_settings()

    return redis.from_url(settings.redis_url, decode_responses=True)


class CircuitBreaker:
    """Per-key breaker stored in Redis (shared across all workers)."""

    def __init__(
        self,
        key: str,
        *,
        failure_threshold: int | None = None,
        open_seconds: float | None = None,
        redis_client: redis.Redis | None = None,
    ) -> None:
        settings = get_settings()

        self._key = f"flowforge:circuit:{key}"
        self._failure_threshold = failure_threshold or settings.circuit_breaker_failure_threshold
        self._open_seconds = open_seconds or settings.circuit_breaker_open_seconds
        self._redis = redis_client or get_sync_redis()

    def _state_key(self) -> str:
        return f"{self._key}:state"

    def _failures_key(self) -> str:
        return f"{self._key}:failures"

    def _opened_at_key(self) -> str:
        return f"{self._key}:opened_at"

    def state(self) -> CircuitState:
        raw = self._redis.get(self._state_key())

        if raw is None:
            return CircuitState.CLOSED

        try:
            return CircuitState(raw)
        except ValueError:
            return CircuitState.CLOSED

    def _transition_open(self) -> None:
        self._redis.set(self._state_key(), CircuitState.OPEN.value)
        self._redis.set(self._opened_at_key(), str(time.time()))

    def _transition_closed(self) -> None:
        pipe = self._redis.pipeline()
        pipe.set(self._state_key(), CircuitState.CLOSED.value)
        pipe.set(self._failures_key(), 0)
        pipe.delete(self._opened_at_key())
        pipe.execute()

    def _maybe_half_open(self) -> CircuitState:
        current = self.state()

        if current != CircuitState.OPEN:
            return current

        opened_raw = self._redis.get(self._opened_at_key())

        if opened_raw is None:
            self._redis.set(self._state_key(), CircuitState.HALF_OPEN.value)

            return CircuitState.HALF_OPEN

        elapsed = time.time() - float(opened_raw)

        if elapsed >= self._open_seconds:
            self._redis.set(self._state_key(), CircuitState.HALF_OPEN.value)

            return CircuitState.HALF_OPEN

        return CircuitState.OPEN

    def allow_request(self) -> CircuitState:
        """Return effective state; raises CircuitOpenError when still open."""

        state = self._maybe_half_open()

        if state == CircuitState.OPEN:
            raise CircuitOpenError(
                f"Circuit open for {self._key!r} — cooling down ({self._open_seconds}s)"
            )

        return state

    def record_success(self) -> None:
        self._transition_closed()

    def record_failure(self) -> None:
        state = self._maybe_half_open()

        if state == CircuitState.HALF_OPEN:
            self._transition_open()

            return

        failures = self._redis.incr(self._failures_key())

        if failures >= self._failure_threshold:
            self._transition_open()

    def call(self, fn) -> object:
        """Run ``fn`` behind the breaker."""

        self.allow_request()

        try:
            result = fn()
        except TransientStepError:
            self.record_failure()

            raise
        except PermanentStepError:
            raise
        except Exception as exc:
            self.record_failure()

            raise TransientStepError(str(exc)) from exc

        self.record_success()

        return result
