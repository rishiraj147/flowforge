"""Import every model here so they register on Base.metadata."""

from flowforge.models.artifact import Artifact
from flowforge.models.dead_letter_task import DeadLetterTask
from flowforge.models.base import Base
from flowforge.models.execution import Execution
from flowforge.models.schedule import Schedule
from flowforge.models.schedule_fire import ScheduleFire
from flowforge.models.task_run import TaskRun
from flowforge.models.user import User
from flowforge.models.webhook import Webhook
from flowforge.models.webhook_delivery import WebhookDelivery
from flowforge.models.workflow import Workflow
from flowforge.models.workflow_version import WorkflowVersion

__all__ = [
    "Base",
    "Artifact",
    "DeadLetterTask",
    "Execution",
    "Schedule",
    "ScheduleFire",
    "TaskRun",
    "User",
    "Webhook",
    "WebhookDelivery",
    "Workflow",
    "WorkflowVersion",
]
