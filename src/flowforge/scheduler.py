"""APScheduler integration — cron triggers inside the FastAPI process."""

from __future__ import annotations

import logging
import uuid

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from flowforge.config import Settings
from flowforge.models import Schedule
from flowforge.services import schedule_service

logger = logging.getLogger(__name__)


class WorkflowCronScheduler:
    """Registers one APScheduler job per enabled schedule.

    Every API replica runs this scheduler; PostgreSQL advisory locks in
    trigger_scheduled_run() ensure only one replica actually creates an execution.
    """

    JOB_PREFIX = "schedule:"

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings
        self._scheduler = AsyncIOScheduler(timezone=settings.scheduler_timezone)

    @property
    def running(self) -> bool:
        return self._scheduler.running

    async def start(self) -> None:
        if not self._settings.scheduler_enabled:
            logger.info("Cron scheduler disabled by configuration")
            return

        self._scheduler.start()
        await self.reload_all()
        logger.info("Cron scheduler started")

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Cron scheduler stopped")

    async def reload_all(self) -> None:
        if not self._settings.scheduler_enabled:
            return

        async with self._sessionmaker() as session:
            result = await session.execute(select(Schedule))
            schedules = list(result.scalars().all())

        for job in self._scheduler.get_jobs():
            if job.id and job.id.startswith(self.JOB_PREFIX):
                job.remove()

        for schedule in schedules:
            if schedule.enabled:
                self._register_job(schedule)

    def remove_schedule_job(self, schedule_id: uuid.UUID) -> None:
        if not self._scheduler.running:
            return

        job_id = self._job_id(schedule_id)

        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)

    async def sync_schedule(self, schedule: Schedule) -> None:
        if not self._settings.scheduler_enabled or not self._scheduler.running:
            return

        job_id = self._job_id(schedule.id)

        if schedule.enabled:
            self._register_job(schedule)
        elif self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)

    def _job_id(self, schedule_id: uuid.UUID) -> str:
        return f"{self.JOB_PREFIX}{schedule_id}"

    def _register_job(self, schedule: Schedule) -> None:
        trigger = CronTrigger.from_crontab(
            schedule.cron_expression,
            timezone=self._settings.scheduler_timezone,
        )

        self._scheduler.add_job(
            self._on_cron_fire,
            trigger=trigger,
            id=self._job_id(schedule.id),
            args=[str(schedule.id)],
            replace_existing=True,
            misfire_grace_time=120,
            coalesce=True,
            max_instances=1,
        )

        logger.debug(
            "Registered cron job %s expression=%s",
            schedule.id,
            schedule.cron_expression,
        )

    async def _on_cron_fire(self, schedule_id: str) -> None:
        schedule_uuid = uuid.UUID(schedule_id)

        async with self._sessionmaker() as session:
            result = await schedule_service.trigger_scheduled_run(
                session,
                schedule_id=schedule_uuid,
            )

        if result.triggered:
            logger.info(
                "Cron fired schedule=%s execution=%s fire_at=%s",
                schedule_id,
                result.execution_id,
                result.fire_at,
            )
        else:
            logger.debug(
                "Cron skipped schedule=%s reason=%s fire_at=%s",
                schedule_id,
                result.reason,
                result.fire_at,
            )
