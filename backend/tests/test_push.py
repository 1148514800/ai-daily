"""Phase 9 tests: push device registration, notifications, and dedupe."""

from __future__ import annotations

import asyncio

import pytest

from app.db.repositories import (
    RUN_SUCCESS,
    TRIGGER_MANUAL,
    TRIGGER_SCHEDULED,
    TRIGGER_STARTUP_CATCHUP,
    DigestRepository,
    PushDeviceRepository,
)
from app.db.session import new_session
from app.jobs.daily_refresh import run_daily_refresh
from app.services.push.schemas import PushResult, PushTicket
from app.services.push.service import build_digest_body, send_digest_notification
from tests.conftest import FROZEN_NOW

TOKEN_A = "ExponentPushToken[aaaaaaaaaaaaaaaaaaaa]"
TOKEN_B = "ExponentPushToken[bbbbbbbbbbbbbbbbbbbb]"
DIGEST_DATE = "2026-09-11"


def register(token: str, platform: str = "android") -> None:
    session = new_session()
    try:
        PushDeviceRepository(session).register(token, platform)
        session.commit()
    finally:
        session.close()


def devices() -> list:
    session = new_session()
    try:
        return PushDeviceRepository(session).list_all()
    finally:
        session.close()


def notified_at(date: str = DIGEST_DATE):
    session = new_session()
    try:
        return DigestRepository(session).notified_at(date)
    finally:
        session.close()


def seed_digest(date: str = DIGEST_DATE) -> None:
    """A push only marks an existing digest, mirroring real refresh order."""
    session = new_session()
    try:
        DigestRepository(session).save(
            date=date, title="t", description="d", news_ids=[], github_ids=[]
        )
        session.commit()
    finally:
        session.close()


class FakePushClient:
    """Records messages and returns a scripted Expo-like response."""

    def __init__(self, tickets: list[PushTicket] | None = None, raises: Exception | None = None):
        self.sent: list = []
        self.tickets = tickets
        self.raises = raises

    def send(self, messages: list) -> PushResult:
        self.sent.extend(messages)
        if self.raises is not None:
            raise self.raises
        if self.tickets is not None:
            return PushResult(tickets=self.tickets)
        return PushResult(tickets=[PushTicket(token=m.to, ok=True) for m in messages])


def ok_tickets(tokens: list[str]) -> list[PushTicket]:
    return [PushTicket(token=token, ok=True) for token in tokens]


def run_outcome(trigger: str, **kwargs):
    return asyncio.run(run_daily_refresh(trigger, **kwargs))


# --- schema upgrade ---


def test_init_db_adds_notified_at_to_existing_database(tmp_path) -> None:
    """A database written by Phase 8 must gain the new column, not crash."""
    from sqlalchemy import create_engine

    from app.db.session import _add_missing_sqlite_columns

    old_engine = create_engine(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
    with old_engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE daily_digests ("
            "date VARCHAR(10) PRIMARY KEY, title TEXT, description TEXT, "
            "created_at DATETIME, updated_at DATETIME)"
        )

    _add_missing_sqlite_columns(old_engine)

    with old_engine.connect() as connection:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(daily_digests)")}
    assert "notified_at" in columns
    assert "title" in columns
    old_engine.dispose()


# --- registration ---


def test_register_push_device(client) -> None:
    response = client.post(
        "/api/v1/push/register",
        json={"expo_push_token": TOKEN_A, "platform": "android"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["platform"] == "android"
    assert payload["enabled"] is True
    assert TOKEN_A not in response.text
    assert payload["token_hint"].startswith("ExponentPu")

    stored = devices()
    assert len(stored) == 1
    assert stored[0].expo_push_token == TOKEN_A
    assert stored[0].last_seen_at is not None


def test_duplicate_register_upserts_single_row(client) -> None:
    first = client.post("/api/v1/push/register", json={"expo_push_token": TOKEN_A})
    second = client.post("/api/v1/push/register", json={"expo_push_token": TOKEN_A})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert len(devices()) == 1


def test_register_reenables_disabled_device(client) -> None:
    client.post("/api/v1/push/register", json={"expo_push_token": TOKEN_A})
    client.delete(f"/api/v1/push/register?expo_push_token={TOKEN_A}")
    assert devices()[0].enabled is False

    client.post("/api/v1/push/register", json={"expo_push_token": TOKEN_A})
    assert devices()[0].enabled is True


def test_register_rejects_invalid_token(client) -> None:
    response = client.post("/api/v1/push/register", json={"expo_push_token": "not-a-token"})
    assert response.status_code == 400
    assert devices() == []


def test_register_rejects_unknown_platform(client) -> None:
    response = client.post(
        "/api/v1/push/register",
        json={"expo_push_token": TOKEN_A, "platform": "blackberry"},
    )
    assert response.status_code == 400


def test_disable_device_keeps_row(client) -> None:
    client.post("/api/v1/push/register", json={"expo_push_token": TOKEN_A})

    response = client.delete(f"/api/v1/push/register?expo_push_token={TOKEN_A}")

    assert response.status_code == 204
    stored = devices()
    assert len(stored) == 1
    assert stored[0].enabled is False


def test_disable_missing_device_returns_404(client) -> None:
    response = client.delete(f"/api/v1/push/register?expo_push_token={TOKEN_A}")
    assert response.status_code == 404


# --- notification content ---


def test_notification_body_omits_zero_github() -> None:
    assert build_digest_body(5, 0) == "今日精选 5 条 AI 动态"
    assert build_digest_body(5, 2) == "今日精选 5 条 AI 动态 · 2 个 GitHub 项目"


# --- sending ---


def test_push_disabled_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUSH_ENABLED", "false")
    register(TOKEN_A)
    fake = FakePushClient()

    report = send_digest_notification(
        date=DIGEST_DATE, news_count=5, github_count=2, client=fake
    )

    assert report.skipped is True
    assert report.skipped_reason == "push disabled"
    assert fake.sent == []


def test_no_devices_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUSH_ENABLED", "true")

    report = send_digest_notification(
        date=DIGEST_DATE, news_count=5, github_count=2, client=FakePushClient()
    )

    assert report.skipped_reason == "no enabled devices"


def test_successful_push_marks_notified(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUSH_ENABLED", "true")
    register(TOKEN_A)
    seed_digest()
    fake = FakePushClient()

    report = send_digest_notification(
        date=DIGEST_DATE, news_count=5, github_count=2, client=fake, force=True
    )

    assert report.delivered == 1
    assert len(fake.sent) == 1
    message = fake.sent[0]
    assert message.title == "AI Daily 已更新"
    assert message.body == "今日精选 5 条 AI 动态 · 2 个 GitHub 项目"
    assert message.data == {"type": "daily_digest", "date": DIGEST_DATE}
    assert message.channel_id == "daily-digest"
    assert notified_at() is not None


def test_partial_device_failure_still_notifies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUSH_ENABLED", "true")
    register(TOKEN_A)
    register(TOKEN_B)
    seed_digest()
    fake = FakePushClient(
        tickets=[
            PushTicket(token=TOKEN_A, ok=True),
            PushTicket(token=TOKEN_B, ok=False, error="bad", details_error="DeviceNotRegistered"),
        ]
    )

    report = send_digest_notification(
        date=DIGEST_DATE, news_count=5, github_count=0, client=fake, force=True
    )

    assert report.delivered == 1
    assert report.failed == 1
    assert notified_at() is not None


def test_device_not_registered_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUSH_ENABLED", "true")
    register(TOKEN_A)
    fake = FakePushClient(
        tickets=[
            PushTicket(token=TOKEN_A, ok=False, error="bad", details_error="DeviceNotRegistered")
        ]
    )

    report = send_digest_notification(
        date=DIGEST_DATE, news_count=5, github_count=0, client=fake, force=True
    )

    assert report.disabled_tokens == [TOKEN_A]
    stored = devices()
    assert stored[0].enabled is False
    # Nothing was delivered, so the day stays eligible for a future attempt.
    assert notified_at() is None


def test_transport_error_is_reported_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.push.client import ExpoPushError

    monkeypatch.setenv("PUSH_ENABLED", "true")
    register(TOKEN_A)
    fake = FakePushClient(raises=ExpoPushError("network down"))

    report = send_digest_notification(
        date=DIGEST_DATE, news_count=5, github_count=0, client=fake, force=True
    )

    assert report.error == "network down"
    assert report.delivered == 0
    assert notified_at() is None


def test_already_notified_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUSH_ENABLED", "true")
    register(TOKEN_A)
    session = new_session()
    try:
        DigestRepository(session).save(
            date=DIGEST_DATE, title="t", description="d", news_ids=[], github_ids=[]
        )
        DigestRepository(session).mark_notified(DIGEST_DATE)
        session.commit()
    finally:
        session.close()

    fake = FakePushClient()
    report = send_digest_notification(
        date=DIGEST_DATE, news_count=5, github_count=0, client=fake
    )

    assert report.skipped_reason == "already notified"
    assert fake.sent == []


# --- refresh integration ---


def test_manual_refresh_does_not_push(patch_rss_feeds, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUSH_ENABLED", "true")
    register(TOKEN_A)
    fake = FakePushClient()
    monkeypatch.setattr("app.services.push.service.ExpoPushClient", lambda *a, **k: fake)

    outcome = run_outcome(TRIGGER_MANUAL, now=FROZEN_NOW)

    assert outcome.status == RUN_SUCCESS
    assert outcome.push is None
    assert fake.sent == []


def test_scheduled_success_pushes(patch_rss_feeds, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUSH_ENABLED", "true")
    register(TOKEN_A)
    fake = FakePushClient()
    monkeypatch.setattr("app.services.push.service.ExpoPushClient", lambda *a, **k: fake)

    outcome = run_outcome(TRIGGER_SCHEDULED, now=FROZEN_NOW)

    assert outcome.status == RUN_SUCCESS
    assert outcome.push is not None
    assert outcome.push.delivered == 1
    assert len(fake.sent) == 1
    assert notified_at() is not None


def test_catchup_success_pushes(patch_rss_feeds, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUSH_ENABLED", "true")
    register(TOKEN_A)
    fake = FakePushClient()
    monkeypatch.setattr("app.services.push.service.ExpoPushClient", lambda *a, **k: fake)

    outcome = run_outcome(TRIGGER_STARTUP_CATCHUP, now=FROZEN_NOW)

    assert outcome.push is not None
    assert outcome.push.delivered == 1


def test_same_digest_is_only_notified_once(
    patch_rss_feeds,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PUSH_ENABLED", "true")
    register(TOKEN_A)
    fake = FakePushClient()
    monkeypatch.setattr("app.services.push.service.ExpoPushClient", lambda *a, **k: fake)

    first = run_outcome(TRIGGER_SCHEDULED, now=FROZEN_NOW)
    second = run_outcome(TRIGGER_STARTUP_CATCHUP, now=FROZEN_NOW)

    assert first.push is not None and first.push.delivered == 1
    assert second.push is not None
    assert second.push.skipped_reason == "already notified"
    assert len(fake.sent) == 1


def test_failed_refresh_does_not_push(patch_rss_feeds, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUSH_ENABLED", "true")
    register(TOKEN_A)
    fake = FakePushClient()
    monkeypatch.setattr("app.services.push.service.ExpoPushClient", lambda *a, **k: fake)

    def boom(*args, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("app.services.refresh_service.store.persist", boom)
    outcome = run_outcome(TRIGGER_SCHEDULED, now=FROZEN_NOW)

    assert outcome.status == "failed"
    assert outcome.push is None
    assert fake.sent == []


def test_push_failure_does_not_fail_refresh(
    patch_rss_feeds,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.push.client import ExpoPushError

    monkeypatch.setenv("PUSH_ENABLED", "true")
    register(TOKEN_A)
    monkeypatch.setattr(
        "app.services.push.service.ExpoPushClient",
        lambda *a, **k: FakePushClient(raises=ExpoPushError("expo down")),
    )

    outcome = run_outcome(TRIGGER_SCHEDULED, now=FROZEN_NOW)

    assert outcome.status == RUN_SUCCESS
    assert outcome.push is not None
    assert outcome.push.error == "expo down"


# --- status and test endpoints ---


def test_push_status_hides_tokens(client) -> None:
    client.post("/api/v1/push/register", json={"expo_push_token": TOKEN_A})

    response = client.get("/api/v1/push/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["registered_devices"] == 1
    assert payload["enabled_devices"] == 1
    assert payload["last_notified_at"] is None
    assert TOKEN_A not in response.text


def test_push_status_reports_last_notified(client) -> None:
    session = new_session()
    try:
        DigestRepository(session).save(
            date=DIGEST_DATE, title="t", description="d", news_ids=[], github_ids=[]
        )
        DigestRepository(session).mark_notified(DIGEST_DATE)
        session.commit()
    finally:
        session.close()

    payload = client.get("/api/v1/push/status").json()
    assert payload["last_notified_at"] is not None


def test_test_endpoint_disabled_by_default(client) -> None:
    response = client.post("/api/v1/push/test")
    assert response.status_code == 403


def test_test_endpoint_requires_devices(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUSH_ENABLED", "true")
    response = client.post("/api/v1/push/test")
    assert response.status_code == 404


def test_test_endpoint_sends_fixed_content(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUSH_ENABLED", "true")
    client.post("/api/v1/push/register", json={"expo_push_token": TOKEN_A})
    fake = FakePushClient()
    monkeypatch.setattr("app.api.v1.ExpoPushClient", lambda *a, **k: fake)

    response = client.post("/api/v1/push/test")

    assert response.status_code == 200
    payload = response.json()
    assert payload["attempted"] == 1
    assert payload["delivered"] == 1
    assert fake.sent[0].title == "AI Daily 已更新"
    assert fake.sent[0].body == "AI Daily 测试通知"


def test_test_endpoint_ignores_client_supplied_content(client, monkeypatch: pytest.MonkeyPatch) -> None:
    """The endpoint must not become an open push relay."""
    monkeypatch.setenv("PUSH_ENABLED", "true")
    client.post("/api/v1/push/register", json={"expo_push_token": TOKEN_A})
    fake = FakePushClient()
    monkeypatch.setattr("app.api.v1.ExpoPushClient", lambda *a, **k: fake)

    client.post(
        "/api/v1/push/test",
        json={"title": "hacked", "body": "spam", "to": "ExponentPushToken[evil]"},
    )

    assert fake.sent[0].body == "AI Daily 测试通知"
    assert fake.sent[0].to == TOKEN_A


def test_test_endpoint_disables_stale_token(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUSH_ENABLED", "true")
    client.post("/api/v1/push/register", json={"expo_push_token": TOKEN_A})
    fake = FakePushClient(
        tickets=[
            PushTicket(token=TOKEN_A, ok=False, error="bad", details_error="DeviceNotRegistered")
        ]
    )
    monkeypatch.setattr("app.api.v1.ExpoPushClient", lambda *a, **k: fake)

    payload = client.post("/api/v1/push/test").json()

    assert payload["delivered"] == 0
    assert devices()[0].enabled is False
