"""S3-compatible object storage client (MinIO in dev, AWS S3 in prod)."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

import boto3
from botocore.client import BaseClient
from botocore.exceptions import ClientError

from flowforge.config import Settings, get_settings

logger = logging.getLogger(__name__)


@lru_cache
def get_s3_client() -> BaseClient:
    settings = get_settings()

    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
    )


def ensure_bucket(settings: Settings | None = None) -> None:
    """Create the artifacts bucket if it does not exist (MinIO local dev)."""

    resolved = settings or get_settings()
    client = get_s3_client()
    bucket = resolved.s3_bucket

    try:
        client.head_bucket(Bucket=bucket)
    except ClientError:
        logger.info("Creating S3 bucket %s", bucket)
        client.create_bucket(Bucket=bucket)


def upload_object(
    *,
    key: str,
    body: bytes,
    content_type: str | None,
    settings: Settings | None = None,
) -> None:
    resolved = settings or get_settings()
    client = get_s3_client()

    extra: dict[str, Any] = {}

    if content_type:
        extra["ContentType"] = content_type

    client.put_object(
        Bucket=resolved.s3_bucket,
        Key=key,
        Body=body,
        **extra,
    )


def object_exists(key: str, settings: Settings | None = None) -> bool:
    resolved = settings or get_settings()
    client = get_s3_client()

    try:
        client.head_object(Bucket=resolved.s3_bucket, Key=key)
    except ClientError:
        return False

    return True


def generate_presigned_download_url(
    key: str,
    *,
    settings: Settings | None = None,
) -> str:
    """Temporary GET URL — browser downloads without API holding long-lived creds."""

    resolved = settings or get_settings()
    client = get_s3_client()

    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": resolved.s3_bucket, "Key": key},
        ExpiresIn=resolved.s3_presign_ttl_seconds,
    )
