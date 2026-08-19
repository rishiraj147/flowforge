"""Artifact storage — S3 bytes + Postgres metadata."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowforge.content_hash import artifact_storage_key, sha256_hex
from flowforge.models import Artifact, Execution, TaskRun
from flowforge.s3_client import (
    generate_presigned_download_url,
    object_exists,
    upload_object,
)


async def get_artifact(
    session: AsyncSession,
    artifact_id: uuid.UUID,
) -> Artifact | None:
    return await session.get(Artifact, artifact_id)


async def list_artifacts_for_execution(
    session: AsyncSession,
    execution_id: uuid.UUID,
) -> list[Artifact] | None:
    execution = await session.get(Execution, execution_id)

    if execution is None:
        return None

    result = await session.execute(
        select(Artifact)
        .where(Artifact.execution_id == execution_id)
        .order_by(Artifact.created_at.asc())
    )

    return list(result.scalars().all())


async def store_artifact(
    session: AsyncSession,
    *,
    data: bytes,
    filename: str,
    content_type: str | None,
    uploaded_by: uuid.UUID,
    execution_id: uuid.UUID | None = None,
    task_run_id: uuid.UUID | None = None,
) -> tuple[Artifact, bool]:
    """Upload bytes to S3 (content-addressed) and record metadata.

    Returns (artifact, deduplicated). If SHA-256 already exists, skips S3 upload.
    """

    if execution_id is not None:
        execution = await session.get(Execution, execution_id)

        if execution is None:
            raise ValueError("execution_not_found")

    if task_run_id is not None:
        task_run = await session.get(TaskRun, task_run_id)

        if task_run is None:
            raise ValueError("task_run_not_found")

    content_hash = sha256_hex(data)
    storage_key = artifact_storage_key(content_hash)
    deduplicated = object_exists(storage_key)

    if not deduplicated:
        upload_object(key=storage_key, body=data, content_type=content_type)

    artifact = Artifact(
        content_hash=content_hash,
        storage_key=storage_key,
        filename=filename,
        content_type=content_type,
        size_bytes=len(data),
        execution_id=execution_id,
        task_run_id=task_run_id,
        uploaded_by=uploaded_by,
    )

    session.add(artifact)
    await session.commit()
    await session.refresh(artifact)

    return artifact, deduplicated


def presigned_download_url(artifact: Artifact) -> str:
    return generate_presigned_download_url(artifact.storage_key)


def store_artifact_sync(
    *,
    data: bytes,
    filename: str,
    content_type: str | None,
    uploaded_by: uuid.UUID,
    execution_id: uuid.UUID | None = None,
    task_run_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Worker-side upload (sync session) — used mid-step execution."""

    from flowforge.sync_db import sync_session

    content_hash = sha256_hex(data)
    storage_key = artifact_storage_key(content_hash)
    session = sync_session()

    try:
        if not object_exists(storage_key):
            upload_object(key=storage_key, body=data, content_type=content_type)

        artifact = Artifact(
            content_hash=content_hash,
            storage_key=storage_key,
            filename=filename,
            content_type=content_type,
            size_bytes=len(data),
            execution_id=execution_id,
            task_run_id=task_run_id,
            uploaded_by=uploaded_by,
        )
        session.add(artifact)
        session.commit()
        session.refresh(artifact)

        return artifact.id
    finally:
        session.close()
