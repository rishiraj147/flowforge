"""Sync Redis publisher — called from Celery workers."""

from __future__ import annotations

import json
import logging
from functools import lru_cache
import uuid
from typing import Any

import redis

from flowforge.config import get_settings
from flowforge.log_channels import execution_log_channel

logger = logging.getLogger(__name__)


@lru_cache
def _redis_client() -> redis.Redis:
    return redis.from_url(
        get_settings().redis_url,
        decode_responses=True,
    )


def publish_execution_log(execution_id: uuid.UUID, event: dict[str, Any]) -> None:
    """PUBLISH one JSON log event. Fire-and-forget; never raises to caller."""

    if not get_settings().log_stream_enabled:
        return

    channel = execution_log_channel(execution_id)

    try:
        _redis_client().publish(channel, json.dumps(event, separators=(",", ":")))
    except redis.RedisError:
        logger.warning("Failed to publish log to %s", channel, exc_info=True)
