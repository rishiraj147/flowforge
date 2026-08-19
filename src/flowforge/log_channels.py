"""Redis Pub/Sub channel names and log event payloads."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

LogLevel = Literal["debug", "info", "warn", "error"]
LogEventType = Literal["log", "status", "heartbeat"]


def execution_log_channel(execution_id: uuid.UUID) -> str:
    """Channel for all log lines from every step in one execution."""

    return f"flowforge:logs:execution:{execution_id}"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_event(
    *,
    execution_id: uuid.UUID,
    task_run_id: uuid.UUID,
    step_id: str,
    message: str,
    level: LogLevel = "info",
) -> dict[str, Any]:
    return {
        "type": "log",
        "execution_id": str(execution_id),
        "task_run_id": str(task_run_id),
        "step_id": step_id,
        "level": level,
        "message": message,
        "timestamp": _utc_now_iso(),
    }


def status_event(
    *,
    execution_id: uuid.UUID,
    task_run_id: uuid.UUID,
    step_id: str,
    status: str,
    error: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": "status",
        "execution_id": str(execution_id),
        "task_run_id": str(task_run_id),
        "step_id": step_id,
        "status": status,
        "timestamp": _utc_now_iso(),
    }

    if error is not None:
        payload["error"] = error

    return payload


def heartbeat_event() -> dict[str, Any]:
    return {"type": "heartbeat", "timestamp": _utc_now_iso()}
