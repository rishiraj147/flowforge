"""Circuit breaker tests (in-memory fake Redis)."""

import pytest

from flowforge.circuit_breaker import CircuitBreaker, CircuitState
from flowforge.exceptions import CircuitOpenError, PermanentStepError, TransientStepError


class _FakePipeline:
    def __init__(self, redis: "_FakeRedis") -> None:
        self._redis = redis
        self._ops: list[tuple[str, tuple]] = []

    def set(self, key: str, value: object) -> None:
        self._ops.append(("set", (key, value)))

    def delete(self, key: str) -> None:
        self._ops.append(("delete", (key,)))

    def execute(self) -> None:
        for op, args in self._ops:
            if op == "set":
                self._redis.set(*args)
            elif op == "delete":
                self._redis.delete(*args)


class _FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def set(self, key: str, value: object) -> None:
        self.data[key] = str(value)

    def incr(self, key: str) -> int:
        current = int(self.data.get(key, "0")) + 1
        self.data[key] = str(current)

        return current

    def delete(self, key: str) -> None:
        self.data.pop(key, None)

    def pipeline(self) -> _FakePipeline:
        return _FakePipeline(self)


def test_circuit_opens_after_threshold_failures():
    redis = _FakeRedis()
    breaker = CircuitBreaker("test-api", failure_threshold=3, open_seconds=60, redis_client=redis)

    for _ in range(3):
        with pytest.raises(TransientStepError):
            breaker.call(lambda: (_raise_transient()))

    assert breaker.state() == CircuitState.OPEN

    with pytest.raises(CircuitOpenError):
        breaker.allow_request()


def test_circuit_closes_after_success():
    redis = _FakeRedis()
    breaker = CircuitBreaker("ok-api", failure_threshold=2, open_seconds=60, redis_client=redis)

    breaker.call(lambda: "ok")

    assert breaker.state() == CircuitState.CLOSED


def test_permanent_errors_do_not_open_circuit():
    redis = _FakeRedis()
    breaker = CircuitBreaker("perm-api", failure_threshold=2, open_seconds=60, redis_client=redis)

    with pytest.raises(PermanentStepError):
        breaker.call(lambda: (_raise_permanent()))

    assert breaker.state() == CircuitState.CLOSED


def _raise_transient() -> None:
    raise TransientStepError("down")


def _raise_permanent() -> None:
    raise PermanentStepError("bad request")
