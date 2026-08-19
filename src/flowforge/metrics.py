"""Prometheus metrics — custom counters/histograms for workflow observability.

HTTP RED metrics (rate, errors, duration) come from prometheus-fastapi-instrumentator.
These metrics cover the workflow domain layer.
"""

from __future__ import annotations

from typing import Literal

from prometheus_client import Counter, Histogram

# --- Counters (always go up; use rate() in Prometheus) ---

WORKFLOWS_TRIGGERED_TOTAL = Counter(
    "workflows_triggered_total",
    "Workflow executions created (one run instance queued).",
    ["trigger_source"],
)

EXECUTIONS_COMPLETED_TOTAL = Counter(
    "executions_completed_total",
    "Executions that reached a terminal state.",
    ["status"],
)

TASK_RUNS_TOTAL = Counter(
    "task_runs_total",
    "Individual step runs finished (success or failed).",
    ["status"],
)

# --- Histogram (distributions — use histogram_quantile for p95 latency) ---

TASK_DURATION_SECONDS = Histogram(
    "task_duration_seconds",
    "Wall-clock seconds from step running → finished.",
    ["step_kind", "status"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
)


def record_workflow_triggered(trigger_source: str) -> None:
    WORKFLOWS_TRIGGERED_TOTAL.labels(trigger_source=trigger_source).inc()


def record_execution_completed(status: Literal["success", "failed"]) -> None:
    EXECUTIONS_COMPLETED_TOTAL.labels(status=status).inc()


def record_task_run_finished(
    *,
    step_kind: str,
    status: Literal["success", "failed"],
    duration_seconds: float,
) -> None:
    TASK_RUNS_TOTAL.labels(status=status).inc()
    TASK_DURATION_SECONDS.labels(step_kind=step_kind, status=status).observe(
        max(duration_seconds, 0.0)
    )


def duration_since(started_at) -> float:
    """Seconds from a timezone-aware started_at to now."""

    if started_at is None:
        return 0.0

    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)

    return max((now - started_at).total_seconds(), 0.0)
