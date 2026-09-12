"""Phase 8 tests: scheduler configuration, refresh runs, and catch-up logic."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from app.db.repositories import (
    RUN_FAILED,
    RUN_SUCCESS,
    TRIGGER_MANUAL,
    TRIGGER_SCHEDULED,
    TRIGGER_STARTUP_CATCHUP,
    RefreshRunRepository,
)
from app.db.session import new_session
from app.jobs import daily_refresh, scheduler
from app.jobs.daily_refresh import (
    is_refresh_running,
    run_daily_refresh,
    should_run_startup_catchup,
)
from app.services.digest_store import store
from app.services.refresh_service import refresh_all
from tests.conftest import FROZEN_NOW, make_fixture_fetch

# 2026-09-11 04:00 in Asia/Shanghai: before the 08:00 default.
BEFORE_SCHEDULED = FROZEN_NOW
# 2026-09-11 10:00 in Asia/Shanghai: after the 08:00 default.
AFTER_SCHEDULED = FROZEN_NOW + timedelta(hours=6)
DIGEST_DATE = "2026-09-11"


def runs() -> list:
    session = new_session()
    try:
        return RefreshRunRepository(session).list_recent(limit=20)
    finally:
        session.close()


def run_outcome(**kwargs):
    return asyncio.run(run_daily_refresh(**kwargs))


# --- scheduler configuration ---


def test_scheduler_disabled_does_not_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    scheduler.shutdown_scheduler()

    assert scheduler.start_scheduler() is None
    assert scheduler.get_scheduler() is None


def test_scheduler_registers_daily_job_with_configured_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("DAILY_REFRESH_HOUR", "7")
    monkeypatch.setenv("DAILY_REFRESH_MINUTE", "30")
    monkeypatch.setenv("APP_TIMEZONE", "Asia/Shanghai")

    built = scheduler.build_scheduler()
    job = built.get_job("daily-refresh")

    assert job is not None
    assert str(job.trigger.timezone) == "Asia/Shanghai"
    fields = {field.name: str(field) for field in job.trigger.fields}
    assert fields["hour"] == "7"
    assert fields["minute"] == "30"
    assert job.coalesce is True
    assert job.max_instances == 1
    assert job.misfire_grace_time == 3600


def test_scheduler_uses_app_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_TIMEZONE", "UTC")
    monkeypatch.setenv("SCHEDULER_ENABLED", "true")

    built = scheduler.build_scheduler()
    job = built.get_job("daily-refresh")
    assert str(job.trigger.timezone) == "UTC"
    assert scheduler.scheduler_state().timezone == "UTC"


def test_scheduler_start_and_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCHEDULER_ENABLED", "true")
    monkeypatch.setattr("app.services.refresh_service.now_utc", lambda: BEFORE_SCHEDULED)
    scheduler.shutdown_scheduler()

    async def scenario() -> None:
        started = scheduler.start_scheduler()
        assert started is not None
        assert started.running is True
        assert scheduler.next_run_at() is not None

    asyncio.run(scenario())
    state = scheduler.scheduler_state()
    assert state.running is True
    assert state.enabled is True

    scheduler.shutdown_scheduler()
    assert scheduler.get_scheduler() is None
    assert scheduler.scheduler_state().running is False


# --- refresh runs ---


def test_manual_refresh_records_success(monkeypatch: pytest.MonkeyPatch, patch_rss_feeds) -> None:
    outcome = run_outcome(trigger=TRIGGER_MANUAL, now=FROZEN_NOW)

    assert outcome.status == RUN_SUCCESS
    assert outcome.date == DIGEST_DATE
    assert outcome.news_count == 6
    assert outcome.github_count > 0

    recorded = runs()
    assert len(recorded) == 1
    assert recorded[0].trigger == TRIGGER_MANUAL
    assert recorded[0].status == RUN_SUCCESS
    assert recorded[0].finished_at is not None
    assert recorded[0].error is None


def test_scheduled_refresh_records_scheduled_trigger(patch_rss_feeds) -> None:
    outcome = run_outcome(trigger=TRIGGER_SCHEDULED, now=FROZEN_NOW)

    assert outcome.status == RUN_SUCCESS
    assert runs()[0].trigger == TRIGGER_SCHEDULED


def test_catchup_refresh_records_catchup_trigger(patch_rss_feeds) -> None:
    outcome = run_outcome(trigger=TRIGGER_STARTUP_CATCHUP, now=FROZEN_NOW)

    assert outcome.status == RUN_SUCCESS
    assert runs()[0].trigger == TRIGGER_STARTUP_CATCHUP


def test_refresh_failure_is_recorded_and_keeps_existing_digest(
    monkeypatch: pytest.MonkeyPatch,
    patch_rss_feeds,
) -> None:
    assert run_outcome(trigger=TRIGGER_MANUAL, now=FROZEN_NOW).status == RUN_SUCCESS
    before = store.get_digest(DIGEST_DATE)

    def boom(*args, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("app.services.refresh_service.store.persist", boom)
    outcome = run_outcome(trigger=TRIGGER_SCHEDULED, now=FROZEN_NOW)

    assert outcome.status == RUN_FAILED
    assert outcome.error == "database unavailable"

    latest = runs()[0]
    assert latest.status == RUN_FAILED
    assert latest.error == "database unavailable"

    after = store.get_digest(DIGEST_DATE)
    assert [item.id for item in after.news] == [item.id for item in before.news]


def test_error_is_truncated_and_has_no_traceback(patch_rss_feeds, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args, **kwargs):
        raise RuntimeError("x" * 900)

    monkeypatch.setattr("app.services.refresh_service.store.persist", boom)
    outcome = run_outcome(trigger=TRIGGER_SCHEDULED, now=FROZEN_NOW)

    assert outcome.status == RUN_FAILED
    stored = runs()[0].error
    assert stored is not None
    assert len(stored) <= 300
    assert "Traceback" not in stored


def test_partial_source_failure_still_succeeds(
    openai_rss_xml: str,
    deepmind_rss_xml: str,
    huggingface_rss_xml: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch = make_fixture_fetch(
        openai_rss_xml,
        deepmind_rss_xml,
        huggingface_rss_xml,
        failing={"deepmind"},
    )
    monkeypatch.setattr("app.collectors.rss.fetch_rss_text", fetch)

    outcome = run_outcome(trigger=TRIGGER_SCHEDULED, now=FROZEN_NOW)

    assert outcome.status == RUN_SUCCESS
    assert outcome.news_count > 0
    failed_sources = [report.source_name for report in outcome.combined.reports if report.error]
    assert failed_sources == ["Google DeepMind"]


def test_llm_failure_does_not_fail_the_run(
    patch_rss_feeds,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(articles):
        raise RuntimeError("llm offline")

    monkeypatch.setattr("app.services.digest_store.enrich_articles", boom)
    outcome = run_outcome(trigger=TRIGGER_SCHEDULED, now=FROZEN_NOW)

    assert outcome.status == RUN_SUCCESS
    assert outcome.news_count == 6


def test_no_content_and_no_digest_records_failed(
    patch_rss_feeds,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.collectors.rss import CollectResult

    monkeypatch.setattr(
        "app.services.digest_store.collect_all_sources",
        lambda **kwargs: [
            CollectResult(source_id="openai", source_name="OpenAI", success=False, error="offline")
        ],
    )
    monkeypatch.setattr("app.services.github_store.github_store.list_projects", lambda: [])

    outcome = run_outcome(trigger=TRIGGER_SCHEDULED, now=FROZEN_NOW)

    assert outcome.status == RUN_FAILED
    assert runs()[0].status == RUN_FAILED


# --- concurrency guard ---


def test_concurrent_refresh_is_skipped(patch_rss_feeds) -> None:
    held = daily_refresh._refresh_lock
    assert held.acquire(blocking=False) is True
    try:
        assert is_refresh_running() is True
        outcome = run_outcome(trigger=TRIGGER_SCHEDULED, now=FROZEN_NOW)
    finally:
        held.release()

    assert outcome.skipped is True
    assert outcome.status == "skipped"
    # A skipped run is never persisted.
    assert runs() == []
    assert is_refresh_running() is False


# --- startup catch-up ---


def test_no_catchup_before_scheduled_time(patch_rss_feeds) -> None:
    assert should_run_startup_catchup(BEFORE_SCHEDULED) is False


def test_catchup_runs_after_scheduled_time_without_success(patch_rss_feeds) -> None:
    assert should_run_startup_catchup(AFTER_SCHEDULED) is True

    outcome = run_outcome(trigger=TRIGGER_STARTUP_CATCHUP, now=AFTER_SCHEDULED)
    assert outcome.status == RUN_SUCCESS
    assert should_run_startup_catchup(AFTER_SCHEDULED) is False


def test_catchup_skipped_when_today_already_succeeded(patch_rss_feeds) -> None:
    assert run_outcome(trigger=TRIGGER_SCHEDULED, now=AFTER_SCHEDULED).status == RUN_SUCCESS

    assert should_run_startup_catchup(AFTER_SCHEDULED) is False


def test_catchup_queues_background_job(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCHEDULER_ENABLED", "true")
    monkeypatch.setattr("app.services.refresh_service.now_utc", lambda: AFTER_SCHEDULED)
    scheduler.shutdown_scheduler()

    async def scenario() -> None:
        started = scheduler.start_scheduler()
        assert started is not None
        assert started.get_job("startup-catchup") is not None

    asyncio.run(scenario())
    scheduler.shutdown_scheduler()


def test_scheduler_still_works_when_digest_already_exists(patch_rss_feeds) -> None:
    """A second run on the same day updates the digest instead of duplicating it."""
    refresh_all(now=FROZEN_NOW)
    outcome = run_outcome(trigger=TRIGGER_SCHEDULED, now=FROZEN_NOW)

    assert outcome.status == RUN_SUCCESS
    assert len(store.list_digest_summaries()) == 1


# --- retry after failure ---


def test_failed_scheduled_run_schedules_one_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCHEDULER_ENABLED", "true")
    monkeypatch.setattr("app.services.refresh_service.now_utc", lambda: BEFORE_SCHEDULED)

    async def fake_run(trigger, **kwargs):
        return daily_refresh.RefreshOutcome(trigger=trigger, status=RUN_FAILED, error="boom")

    monkeypatch.setattr("app.jobs.scheduler.run_daily_refresh", fake_run)
    scheduler.shutdown_scheduler()

    async def scenario() -> None:
        started = scheduler.start_scheduler()
        assert started is not None
        assert started.get_job("daily-refresh-retry") is None

        await scheduler._scheduled_job()
        retry = started.get_job("daily-refresh-retry")
        assert retry is not None

        # A second failure replaces the pending retry instead of stacking more.
        await scheduler._scheduled_job()
        retry_jobs = [job for job in started.get_jobs() if job.id == "daily-refresh-retry"]
        assert len(retry_jobs) == 1

    asyncio.run(scenario())
    scheduler.shutdown_scheduler()


def test_successful_run_does_not_schedule_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCHEDULER_ENABLED", "true")
    monkeypatch.setattr("app.services.refresh_service.now_utc", lambda: BEFORE_SCHEDULED)

    async def fake_run(trigger, **kwargs):
        return daily_refresh.RefreshOutcome(trigger=trigger, status=RUN_SUCCESS)

    monkeypatch.setattr("app.jobs.scheduler.run_daily_refresh", fake_run)
    scheduler.shutdown_scheduler()

    async def scenario() -> None:
        started = scheduler.start_scheduler()
        assert started is not None
        await scheduler._scheduled_job()
        assert started.get_job("daily-refresh-retry") is None

    asyncio.run(scenario())
    scheduler.shutdown_scheduler()


def test_skipped_run_does_not_schedule_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCHEDULER_ENABLED", "true")
    monkeypatch.setattr("app.services.refresh_service.now_utc", lambda: BEFORE_SCHEDULED)

    async def fake_run(trigger, **kwargs):
        return daily_refresh.RefreshOutcome(trigger=trigger, status="skipped")

    monkeypatch.setattr("app.jobs.scheduler.run_daily_refresh", fake_run)
    scheduler.shutdown_scheduler()

    async def scenario() -> None:
        started = scheduler.start_scheduler()
        assert started is not None
        await scheduler._scheduled_job()
        assert started.get_job("daily-refresh-retry") is None

    asyncio.run(scenario())
    scheduler.shutdown_scheduler()


# --- status API ---


def test_refresh_status_endpoint(client) -> None:
    response = client.get("/api/v1/refresh/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["scheduler_enabled"] is False
    assert payload["timezone"] == "Asia/Shanghai"
    assert payload["scheduled_time"] == "08:00"
    assert payload["is_running"] is False
    assert payload["last_run"] is None
    assert payload["next_run_at"] is None


def test_refresh_status_reports_last_run(client) -> None:
    outcome = run_outcome(trigger=TRIGGER_MANUAL, now=FROZEN_NOW)
    assert outcome.status == RUN_SUCCESS

    payload = client.get("/api/v1/refresh/status").json()
    last_run = payload["last_run"]
    assert last_run["status"] == RUN_SUCCESS
    assert last_run["trigger"] == TRIGGER_MANUAL
    assert last_run["news_count"] == 6
    assert last_run["finished_at"]
    assert last_run["error"] is None


def test_refresh_status_hides_secrets(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_supersecret")
    monkeypatch.setenv("LLM_API_KEY", "sk-supersecret")

    body = client.get("/api/v1/refresh/status").text
    assert "supersecret" not in body
