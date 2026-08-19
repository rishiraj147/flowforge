"""Pydantic schemas for dead-letter queue."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class DeadLetterTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_run_id: uuid.UUID
    celery_task_id: str | None
    task_name: str
    error: str
    traceback: str | None
    retry_count: int
    payload: dict[str, Any] | None
    status: Literal["pending", "replayed"]
    created_at: datetime
    replayed_at: datetime | None


class BackoffPreviewRead(BaseModel):
    attempt: int
    base_seconds: float
    max_seconds: float
    delay_without_jitter: float
    delay_with_jitter: float
    formula: str
    celery_equivalent: str
