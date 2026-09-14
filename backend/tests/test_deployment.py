"""Phase 10 tests: local deployment, dormant push, and system status."""

from __future__ import annotations

import asyncio

import pytest

from app.config.push import push_enabled
from app.db.repositories import TRIGGER_SCHEDULED
from app.jobs.daily_refresh import run_daily_refresh
from tests.conftest import FROZEN_NOW


def run_outcome(trigger: str, **kwargs):
    return asyncio.run(run_daily_refresh(trigger, **kwargs))


# --- dormant push ---


def test_push_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PUSH_ENABLED", raising=False)
    assert push_enabled() is False


def test_push_disabled_does_not_break_scheduled_refresh(
    patch_rss_feeds,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The daily job must succeed with push off, and never attempt a send."""
    monkeypatch.setenv("PUSH_ENABLED", "false")

    def explode(*args, **kwargs):
        raise AssertionError("push must not run while disabled")

    monkeypatch.setattr("app.services.push.service.ExpoPushClient", explode)

    outcome = run_outcome(TRIGGER_SCHEDULED, now=FROZEN_NOW)

    assert outcome.status == "success"
    assert outcome.news_count > 0
    assert outcome.push is not None
    assert outcome.push.skipped is True
    assert outcome.push.skipped_reason == "push disabled"


def test_push_status_endpoint_reports_disabled(client) -> None:
    payload = client.get("/api/v1/push/status").json()
    assert payload["push_enabled"] is False
    assert payload["registered_devices"] == 0


def test_push_register_endpoint_still_works_while_disabled(client) -> None:
    """The endpoint is dormant, not removed, so it stays callable for later."""
    response = client.post(
        "/api/v1/push/register",
        json={"expo_push_token": "ExponentPushToken[testtoken0000000000]"},
    )
    assert response.status_code == 200


# --- system status ---


def test_system_status_reports_ok(client) -> None:
    payload = client.get("/api/v1/system/status").json()

    assert payload["status"] == "ok"
    assert payload["database"] == "ok"
    assert payload["scheduler_enabled"] is False
    assert payload["last_refresh_status"] in {"success", "failed", None}


def test_system_status_never_leaks_configuration(
    client, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A deployment health check must not echo secrets or connection strings."""
    monkeypatch.setenv("LLM_API_KEY", "sk-super-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp-secret-token")
    # A URL that looks like production, so the check would catch it if the route
    # echoed its connection string. It is not the real default file: tests are
    # forbidden from pointing at that at all (see the isolation tests below).
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'secret.db').as_posix()}")

    response = client.get("/api/v1/system/status")

    assert response.status_code == 200
    assert "sk-super-secret" not in response.text
    assert "ghp-secret-token" not in response.text
    assert "sqlite" not in response.text


def test_health_still_returns_plain_ok(client) -> None:
    assert client.get("/health").json() == {"status": "ok"}
