"""Celery task modules. Import here so worker autoload sees every task."""

from flowforge.tasks.demo import demo_slow_task
from flowforge.tasks.execution import execute_step_task

__all__ = ["demo_slow_task", "execute_step_task"]
