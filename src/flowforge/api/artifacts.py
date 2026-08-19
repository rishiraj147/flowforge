"""Artifact upload and presigned download endpoints."""

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from flowforge.authz import Permission, require_permission
from flowforge.config import Settings, settings_from_request
from flowforge.db import get_session
from flowforge.models import User
from flowforge.schemas.artifact import (
    ArtifactRead,
    ArtifactUploadResult,
    PresignedDownloadRead,
)
from flowforge.services import artifact_service, execution_service

router = APIRouter(tags=["artifacts"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


def _artifact_read(artifact, deduplicated: bool = False) -> ArtifactRead:
    return ArtifactRead(
        id=artifact.id,
        content_hash=artifact.content_hash,
        filename=artifact.filename,
        content_type=artifact.content_type,
        size_bytes=artifact.size_bytes,
        execution_id=artifact.execution_id,
        task_run_id=artifact.task_run_id,
        uploaded_by=artifact.uploaded_by,
        created_at=artifact.created_at,
        deduplicated=deduplicated,
    )


@router.post(
    "/executions/{execution_id}/artifacts",
    response_model=ArtifactUploadResult,
    status_code=status.HTTP_201_CREATED,
)
async def upload_execution_artifact(
    execution_id: uuid.UUID,
    file: UploadFile = File(...),
    task_run_id: uuid.UUID | None = None,
    current_user: User = Depends(require_permission(Permission.ARTIFACTS_WRITE)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(settings_from_request),
) -> ArtifactUploadResult:
    """Upload a file; stored in S3 by SHA-256 hash (deduplicated)."""

    if not settings.s3_enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Object storage is disabled",
        )

    execution = await execution_service.get_execution(session, execution_id)

    if execution is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found")

    data = await file.read()

    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty file")

    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File too large")

    try:
        artifact, deduplicated = await artifact_service.store_artifact(
            session,
            data=data,
            filename=file.filename or "upload.bin",
            content_type=file.content_type,
            uploaded_by=current_user.id,
            execution_id=execution_id,
            task_run_id=task_run_id,
        )
    except ValueError as exc:
        if str(exc) == "task_run_not_found":
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Task run not found") from exc

        raise

    return ArtifactUploadResult(artifact=_artifact_read(artifact, deduplicated))


@router.get(
    "/executions/{execution_id}/artifacts",
    response_model=list[ArtifactRead],
)
async def list_execution_artifacts(
    execution_id: uuid.UUID,
    _r: User = Depends(require_permission(Permission.ARTIFACTS_READ)),
    session: AsyncSession = Depends(get_session),
) -> list[ArtifactRead]:
    artifacts = await artifact_service.list_artifacts_for_execution(
        session,
        execution_id,
    )

    if artifacts is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found")

    return [_artifact_read(a) for a in artifacts]


@router.get(
    "/artifacts/{artifact_id}",
    response_model=ArtifactRead,
)
async def get_artifact(
    artifact_id: uuid.UUID,
    _r: User = Depends(require_permission(Permission.ARTIFACTS_READ)),
    session: AsyncSession = Depends(get_session),
) -> ArtifactRead:
    artifact = await artifact_service.get_artifact(session, artifact_id)

    if artifact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Artifact not found")

    return _artifact_read(artifact)


@router.get(
    "/artifacts/{artifact_id}/download-url",
    response_model=PresignedDownloadRead,
)
async def get_artifact_download_url(
    artifact_id: uuid.UUID,
    _r: User = Depends(require_permission(Permission.ARTIFACTS_READ)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(settings_from_request),
) -> PresignedDownloadRead:
    """Return a short-lived presigned URL — no S3 credentials in the browser."""

    if not settings.s3_enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Object storage is disabled",
        )

    artifact = await artifact_service.get_artifact(session, artifact_id)

    if artifact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Artifact not found")

    url = artifact_service.presigned_download_url(artifact)

    return PresignedDownloadRead(
        artifact_id=artifact.id,
        url=url,
        expires_in_seconds=settings.s3_presign_ttl_seconds,
    )
