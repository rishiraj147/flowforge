"""Pydantic schemas for artifacts."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    content_hash: str
    filename: str
    content_type: str | None
    size_bytes: int
    execution_id: uuid.UUID | None
    task_run_id: uuid.UUID | None
    uploaded_by: uuid.UUID
    created_at: datetime
    deduplicated: bool = False


class PresignedDownloadRead(BaseModel):
    artifact_id: uuid.UUID
    url: str
    expires_in_seconds: int = Field(description="Presigned URL lifetime")


class ArtifactUploadResult(BaseModel):
    artifact: ArtifactRead
