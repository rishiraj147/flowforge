"""Demo endpoints for Celery queue behavior (Step 2.4)."""

from fastapi import APIRouter, Query

from flowforge.tasks.demo import demo_slow_task

router = APIRouter(prefix="/demo", tags=["demo"])


@router.post("/slow")
async def queue_slow_demo(
    seconds: int = Query(
        default=10,
        ge=1,
        le=300,
        description="How long the worker should sleep once it picks up the job.",
    ),
) -> dict[str, bool | str]:
    """Enqueue a slow job and return immediately.

    The HTTP handler does NOT sleep — it only publishes a message to Redis.
    A Celery worker process must be running to execute the task.
    """

    async_result = demo_slow_task.delay(seconds)

    return {
        "queued": True,
        "task_id": async_result.id,
    }
