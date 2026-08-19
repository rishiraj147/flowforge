"""Step execution errors — transient vs permanent (retry policy)."""


class TransientStepError(Exception):
    """Temporary failure — safe to retry (network blip, 503, simulated flake)."""


class PermanentStepError(Exception):
    """Logical / validation failure — retrying will not help."""


class CircuitOpenError(Exception):
    """Circuit breaker is open — downstream is unhealthy; do not retry yet."""
