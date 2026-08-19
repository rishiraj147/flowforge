"""Demo tasks for learning Celery (Step 2.4).

Real workflow execution tasks will live alongside these in later phases.
"""

import time
from typing import Any

from flowforge.celery_app import celery_app


@celery_app.task(name="flowforge.demo_slow")
def demo_slow_task(seconds: int = 10) -> dict[str, Any]:
    """Sleep synchronously in the WORKER process — never in the FastAPI handler."""

    time.sleep(seconds)

    return {
        "status": "done",
        "seconds": seconds,
    }
