from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.cron import CronTrigger

from app.config.schedule import (
    DAILY_REFRESH_JOB_ID,
    daily_refresh_hour,
    daily_refresh_minute,
    misfire_grace_seconds,
    retry_delay_minutes,
    schedule_timezone,
    scheduler_enabled,
)
from app.config.timezone import app_timezone_name
from app.db.repositories import TRIGGER_SCHEDULED, TRIGGER_STARTUP_CATCHUP
from app.jobs.daily_refresh import (
    RefreshOutcome,
    run_daily_refresh,
    should_run_startup_catchup,
)
from app.services import refresh_service

logger = logging.getLogger(__name__)

RETRY_JOB_ID = "daily-refresh-retry"


@dataclass
class SchedulerState:
    """Small, serialisable view of the scheduler for the status API."""

    enabled: bool
    running: bool
    timezone: str
    scheduled_time: str
    next_run_at: str | None


_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler | None:
    return _scheduler


async def _scheduled_job() -> None:
    outcome = await run_daily_refresh(TRIGGER_SCHEDULED)
    if outcome.skipped or outcome.succeeded:
        return
    _schedule_retry()


def _schedule_retry() -> None:
    """Retry a failed scheduled run once, then wait for the next normal slot."""
    scheduler = _scheduler
    if scheduler is None:
        return
    run_at = _now() + timedelta(minutes=retry_delay_minutes())
    scheduler.add_job(
        _retry_job,
        trigger=DateTrigger(run_date=run_at),
        id=RETRY_JOB_ID,
        name="AI Daily retry",
        replace_existing=True,
        misfire_grace_time=misfire_grace_seconds(),
    )
    logger.warning("Refresh failed; scheduled one retry at %s", run_at.isoformat())


async def _retry_job() -> None:
    await run_daily_refresh(TRIGGER_SCHEDULED)


async def _catchup_job() -> None:
    await run_daily_refresh(TRIGGER_STARTUP_CATCHUP)


def _now():
    # Read through the module so tests can freeze time by patching it.
    return refresh_service.now_utc()


def build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=schedule_timezone())
    scheduler.add_job(
        _scheduled_job,
        trigger=CronTrigger(
            hour=daily_refresh_hour(),
            minute=daily_refresh_minute(),
            timezone=schedule_timezone(),
        ),
        id=DAILY_REFRESH_JOB_ID,
        name="AI Daily refresh",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=misfire_grace_seconds(),
    )
    return scheduler


def start_scheduler() -> AsyncIOScheduler | None:
    """Start the daily job and trigger a catch-up run when today was missed."""
    global _scheduler
    if not scheduler_enabled():
        logger.info("Scheduler disabled via SCHEDULER_ENABLED")
        return None
    if _scheduler is not None:
        return _scheduler

    scheduler = build_scheduler()
    scheduler.start()
    _scheduler = scheduler
    logger.info(
        "Scheduler started timezone=%s scheduled_time=%02d:%02d",
        app_timezone_name(),
        daily_refresh_hour(),
        daily_refresh_minute(),
    )
    trigger_catchup_if_needed(scheduler)
    return scheduler


def trigger_catchup_if_needed(scheduler: AsyncIOScheduler | None = None) -> bool:
    """Queue a background catch-up run when today's refresh never succeeded."""
    target = scheduler or _scheduler
    if target is None:
        return False
    if not should_run_startup_catchup():
        return False

    target.add_job(
        _catchup_job,
        trigger=DateTrigger(run_date=_now()),
        id="startup-catchup",
        name="AI Daily startup catch-up",
        replace_existing=True,
        misfire_grace_time=misfire_grace_seconds(),
    )
    logger.info("Startup catch-up scheduled: today has no successful refresh yet")
    return True


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is None:
        return
    try:
        _scheduler.shutdown(wait=False)
    except Exception:
        logger.exception("scheduler shutdown failed")
    finally:
        _scheduler = None
        logger.info("Scheduler stopped")


def next_run_at() -> str | None:
    scheduler = _scheduler
    if scheduler is None:
        return None
    job = scheduler.get_job(DAILY_REFRESH_JOB_ID)
    if job is None or job.next_run_time is None:
        return None
    return job.next_run_time.isoformat()


def scheduler_state() -> SchedulerState:
    from app.config.schedule import scheduled_time_label

    scheduler = _scheduler
    return SchedulerState(
        enabled=scheduler_enabled(),
        running=bool(scheduler and scheduler.running),
        timezone=app_timezone_name(),
        scheduled_time=scheduled_time_label(),
        next_run_at=next_run_at(),
    )


__all__ = [
    "RefreshOutcome",
    "SchedulerState",
    "build_scheduler",
    "get_scheduler",
    "next_run_at",
    "scheduler_state",
    "shutdown_scheduler",
    "start_scheduler",
    "trigger_catchup_if_needed",
]
