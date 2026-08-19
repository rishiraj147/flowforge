"""Backpressure queue behavior."""

import asyncio

import pytest

from flowforge.log_stream import _enqueue_with_backpressure


@pytest.mark.asyncio
async def test_backpressure_drops_oldest_when_full():
    queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=2)

    await _enqueue_with_backpressure(queue, {"seq": 1})
    await _enqueue_with_backpressure(queue, {"seq": 2})
    await _enqueue_with_backpressure(queue, {"seq": 3})

    first = await queue.get()

    assert first["seq"] == 2
    second = await queue.get()

    assert second["seq"] == 3
