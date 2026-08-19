"""Pydantic schemas for cron schedules."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ScheduleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    cron_expression: str = Field(min_length=1, max_length=100)
    enabled: bool = True


class ScheduleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    cron_expression: str | None = Field(default=None, min_length=1, max_length=100)
    enabled: bool | None = None


class ScheduleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workflow_id: uuid.UUID
    name: str
    cron_expression: str
    enabled: bool
    owner_id: uuid.UUID
    last_triggered_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CronDecodeQuery(BaseModel):
    expression: str = Field(min_length=1, max_length=100)


class CronDecodeRead(BaseModel):
    expression: str
    summary: str
    fields: dict[str, Any]
    next_runs_utc: list[str]


class ScheduleTriggerResult(BaseModel):
    triggered: bool
    reason: str | None = None
    execution_id: uuid.UUID | None = None
    fire_at: datetime | None = None
