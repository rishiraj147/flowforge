"""Bridge Redis Pub/Sub log events to a WebSocket with backpressure."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

import redis.asyncio as aioredis
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from flowforge.config import Settings
from flowforge.log_channels import execution_log_channel, heartbeat_event

logger = logging.getLogger(__name__)


async def _enqueue_with_backpressure(
    queue: asyncio.Queue[dict[str, Any]],
    event: dict[str, Any],
) -> None:
    """Drop oldest line if the browser is slower than the worker (backpressure)."""

    try:
        queue.put_nowait(event)
    except asyncio.QueueFull:
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass

        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.debug("Log stream queue full; dropping event")


async def _redis_listener(
    redis_url: str,
    channel: str,
    queue: asyncio.Queue[dict[str, Any]],
) -> None:
    client = aioredis.from_url(redis_url, decode_responses=True)
    pubsub = client.pubsub()

    try:
        await pubsub.subscribe(channel)

        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=1.0,
            )

            if message is None:
                continue

            if message.get("type") != "message":
                continue

            data = message.get("data")

            if not isinstance(data, str):
                continue

            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                continue

            if isinstance(event, dict):
                await _enqueue_with_backpressure(queue, event)
    except asyncio.CancelledError:
        raise
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
        await client.aclose()


async def _heartbeat_to_queue(
    queue: asyncio.Queue[dict[str, Any]],
    interval_seconds: int,
) -> None:
    try:
        while True:
            await asyncio.sleep(interval_seconds)
            await _enqueue_with_backpressure(queue, heartbeat_event())
    except asyncio.CancelledError:
        raise


async def _queue_sender(
    websocket: WebSocket,
    queue: asyncio.Queue[dict[str, Any]],
) -> None:
    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except asyncio.CancelledError:
        raise
    except (WebSocketDisconnect, RuntimeError):
        # Client disconnected while sending.
        return


async def _shutdown_tasks(tasks: list[asyncio.Task[None]]) -> None:
    for task in tasks:
        task.cancel()

    await asyncio.gather(*tasks, return_exceptions=True)


async def stream_execution_logs(
    websocket: WebSocket,
    execution_id: uuid.UUID,
    settings: Settings,
) -> None:
    """Subscribe to Redis and forward log events until the client disconnects."""

    if not settings.log_stream_enabled:
        await websocket.close(code=1008, reason="Log streaming disabled")
        return

    channel = execution_log_channel(execution_id)
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
        maxsize=settings.log_stream_max_queue,
    )

    listener = asyncio.create_task(
        _redis_listener(settings.redis_url, channel, queue),
        name=f"log-redis-{execution_id}",
    )
    sender = asyncio.create_task(
        _queue_sender(websocket, queue),
        name=f"log-send-{execution_id}",
    )
    heartbeat = asyncio.create_task(
        _heartbeat_to_queue(queue, settings.log_stream_heartbeat_seconds),
        name=f"log-heartbeat-{execution_id}",
    )
    tasks = [listener, sender, heartbeat]

    try:
        while True:
            try:
                await websocket.receive_text()
            except WebSocketDisconnect:
                break
    finally:
        await _shutdown_tasks(tasks)
