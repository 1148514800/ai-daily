from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime

from app.config.schedule import (
    daily_refresh_hour,
    daily_refresh_minute,
    schedule_timezone,
)
from app.config.timezone import app_timezone_name, digest_date_for
from app.db.repositories import (
    RUN_FAILED,
    RUN_SUCCESS,
    TRIGGER_MANUAL,
    RefreshRunRepository,
)
from app.db.session import new_session
from app.services import refresh_service
from app.services.digest_store import store
from app.services.refresh_service import CombinedRefresh, refresh_all

logger = logging.getLogger(__name__)

# Not persisted: a skipped run never touches the database.
RUN_SKIPPED = "skipped"

MAX_ERROR_LENGTH = 300

# A threading lock is used because the collection work runs in a worker thread
# and because CLI runs create their own event loop. It is loop independent and
# still guarantees that two refreshes never write at the same time.
_refresh_lock = threading.Lock()


@dataclass
class RefreshOutcome:
    trigger: str
    status: str
    date: str | None = None
    run_id: int | None = None
    saved: bool = False
    news_count: int = 0
    github_count: int = 0
    duration_seconds: float = 0.0
    error: str | None = None
    combined: CombinedRefresh | None = None

    @property
    def skipped(self) -> bool:
        return self.status == RUN_SKIPPED

    @property
    def succeeded(self) -> bool:
        return self.status == RUN_SUCCESS


def is_refresh_running() -> bool:
    return _refresh_lock.locked()


def _short_error(error: object) -> str | None:
    """Keep the stored reason short; full traceback stays in the log."""
    if error is None:
        return None
    text = " ".join(str(error).split())
    if not text:
        return None
    return text[:MAX_ERROR_LENGTH]


def _record_start(trigger: str) -> int | None:
    session = new_session()
    try:
        row = RefreshRunRepository(session).start(trigger)
        session.commit()
        return row.id
    except Exception:
        session.rollback()
        logger.exception("could not record refresh run start trigger=%s", trigger)
        return None
    finally:
        session.close()


def _record_finish(outcome: RefreshOutcome) -> None:
    if outcome.run_id is None:
        return
    session = new_session()
    try:
        RefreshRunRepository(session).finish(
            outcome.run_id,
            status=outcome.status,
            news_count=outcome.news_count,
            github_count=outcome.github_count,
            error=outcome.error,
            digest_date=outcome.date,
        )
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("could not record refresh run finish run_id=%s", outcome.run_id)
    finally:
        session.close()


def _source_failures(combined: CombinedRefresh) -> list[str]:
    return [report.source_name for report in combined.reports if report.error]


def _evaluate(combined: CombinedRefresh) -> tuple[str, str | None, int, int]:
    """Decide the run status from what actually reached the database.

    A run only counts as successful when a digest with real content landed, so a
    total collector outage is visible as a failure instead of a silent success.
    """
    date = combined.date
    if combined.saved:
        news_count = store.last_news_count
        github_count = store.last_github_count
        if news_count or github_count:
            return RUN_SUCCESS, None, news_count, github_count
        return RUN_FAILED, "refresh produced no content", news_count, github_count

    digest = store.get_by_date(date)
    if digest is not None:
        news_count = len(digest.news)
        github_count = len(digest.github_projects)
        if news_count or github_count:
            return (
                RUN_FAILED,
                "no new content collected; kept the existing digest",
                news_count,
                github_count,
            )
    return RUN_FAILED, "refresh produced no digest", 0, 0


def _execute_refresh(
    trigger: str,
    now: datetime | None,
    fetch_text,
    fetch_trending,
    github_client,
    enrich,
) -> RefreshOutcome:
    started = time.monotonic()
    outcome = RefreshOutcome(trigger=trigger, status=RUN_FAILED)
    outcome.run_id = _record_start(trigger)
    logger.info("Refresh started trigger=%s timezone=%s", trigger, app_timezone_name())

    try:
        combined = refresh_all(
            now=now,
            fetch_text=fetch_text,
            fetch_trending=fetch_trending,
            github_client=github_client,
            enrich=enrich,
        )
    except Exception as exc:
        logger.exception("refresh failed trigger=%s", trigger)
        outcome.status = RUN_FAILED
        outcome.error = _short_error(exc)
        outcome.duration_seconds = time.monotonic() - started
        _record_finish(outcome)
        return outcome

    outcome.combined = combined
    outcome.date = combined.date
    status, error, news_count, github_count = _evaluate(combined)
    outcome.status = status
    outcome.error = error
    outcome.news_count = news_count
    outcome.github_count = github_count
    outcome.saved = combined.saved
    outcome.duration_seconds = time.monotonic() - started

    for source_name in _source_failures(combined):
        logger.warning("source failed during refresh source=%s trigger=%s", source_name, trigger)
    if outcome.status == RUN_SUCCESS:
        logger.info(
            "Refresh success trigger=%s date=%s news=%s github=%s duration=%.1fs",
            trigger,
            outcome.date,
            news_count,
            github_count,
            outcome.duration_seconds,
        )
    else:
        logger.warning(
            "Refresh failed trigger=%s date=%s reason=%s",
            trigger,
            outcome.date,
            outcome.error,
        )

    _record_finish(outcome)
    return outcome


async def run_daily_refresh(
    trigger: str = TRIGGER_MANUAL,
    *,
    now: datetime | None = None,
    fetch_text=None,
    fetch_trending=None,
    github_client=None,
    enrich=None,
) -> RefreshOutcome:
    """Run one refresh, guarded so two runs never write at the same time.

    Collection is blocking, so the work happens in a worker thread and the
    event loop stays free for FastAPI requests.
    """
    if _refresh_lock.locked():
        logger.warning("Refresh skipped: another refresh is already running")
        return RefreshOutcome(trigger=trigger, status=RUN_SKIPPED)

    # Non-blocking acquire: a second caller skips instead of queueing up.
    if not _refresh_lock.acquire(blocking=False):
        logger.warning("Refresh skipped: another refresh is already running")
        return RefreshOutcome(trigger=trigger, status=RUN_SKIPPED)
    try:
        return await asyncio.to_thread(
            _execute_refresh,
            trigger,
            now,
            fetch_text,
            fetch_trending,
            github_client,
            enrich,
        )
    finally:
        _refresh_lock.release()


def run_manual_refresh(**kwargs) -> RefreshOutcome:
    """Synchronous entry point for the CLI."""
    return asyncio.run(run_daily_refresh(TRIGGER_MANUAL, **kwargs))


def should_run_startup_catchup(now: datetime | None = None) -> bool:
    """True when today's scheduled time has passed without a successful run."""
    # Read through the module so tests can freeze time by patching it.
    current = now or refresh_service.now_utc()
    local = current.astimezone(schedule_timezone())
    scheduled = local.replace(
        hour=daily_refresh_hour(),
        minute=daily_refresh_minute(),
        second=0,
        microsecond=0,
    )
    if local < scheduled:
        return False

    date = digest_date_for(current)
    session = new_session()
    try:
        return not RefreshRunRepository(session).has_success_for_date(date)
    finally:
        session.close()
