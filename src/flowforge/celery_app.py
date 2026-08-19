"""Celery application factory.

The worker is a SEPARATE process from uvicorn:

    poetry run celery -A flowforge.celery_app:celery_app worker --loglevel=info

`broker_url` / `result_backend` both point at Redis (docker-compose). The API
enqueues via task.delay(); workers poll Redis and execute tasks synchronously
in the worker process.
"""

from kombu import Exchange, Queue

from celery import Celery

from flowforge.config import get_settings


def create_celery_app() -> Celery:
    settings = get_settings()

    app = Celery(
        "flowforge",
        include=["flowforge.tasks.demo", "flowforge.tasks.execution", "flowforge.tasks.notifications"],
    )

    app.conf.update(
        broker_url=settings.redis_url,
        result_backend=settings.redis_url,
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        task_queues=(
            Queue("celery", Exchange("celery"), routing_key="celery"),
            Queue("dead_letter", Exchange("dead_letter"), routing_key="dead_letter"),
        ),
    )

    return app


celery_app = create_celery_app()

from flowforge.tasks.execution import execute_step_task  # noqa: E402

_retry_settings = get_settings()
execute_step_task.max_retries = _retry_settings.retry_max_retries
execute_step_task.retry_backoff = _retry_settings.retry_backoff_base_seconds
execute_step_task.retry_backoff_max = _retry_settings.retry_backoff_max_seconds
