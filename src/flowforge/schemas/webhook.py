"""Pydantic schemas for webhooks."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class WebhookCreate(BaseModel):
    enabled: bool = True


class WebhookRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workflow_id: uuid.UUID
    token: str
    url_path: str
    enabled: bool
    owner_id: uuid.UUID
    last_triggered_at: datetime | None
    created_at: datetime
    updated_at: datetime


class WebhookCreated(BaseModel):
    """Returned only on create / rotate — includes secret once."""

    webhook: WebhookRead
    secret: str = Field(description="HMAC signing secret — store securely; not shown again")


class WebhookUpdate(BaseModel):
    enabled: bool | None = None


class WebhookDeliveryResult(BaseModel):
    triggered: bool
    duplicate: bool = False
    execution_id: uuid.UUID | None = None
    reason: str | None = None
