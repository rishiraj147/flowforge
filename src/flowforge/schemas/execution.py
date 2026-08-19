"""Pydantic schemas for executions and task runs."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ExecutionCreate(BaseModel):
    """Optional body for POST /workflows/{id}/executions (no fields for now)."""


class ExecutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workflow_id: uuid.UUID
    workflow_version_id: uuid.UUID
    status: str
    triggered_by: uuid.UUID
    trigger_source: Literal["manual", "schedule", "webhook"] = "manual"
    schedule_id: uuid.UUID | None = None
    webhook_id: uuid.UUID | None = None
    created_at: datetime
    finished_at: datetime | None


class TaskRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    execution_id: uuid.UUID
    step_id: str
    status: Literal["pending", "queued", "running", "success", "failed"]
    celery_task_id: str | None
    retry_count: int = 0
    output: dict[str, Any] | None
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class StepRunRequest(BaseModel):
    """Body for POST /executions/{id}/run-step when not using path param."""

    step_id: str = Field(min_length=1, max_length=255)
