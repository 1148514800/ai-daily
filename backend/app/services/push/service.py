from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.config.push import notification_channel_id, push_enabled
from app.db.repositories import DigestRepository, PushDeviceRepository
from app.db.session import new_session
from app.services.push.client import ExpoPushClient, ExpoPushError
from app.services.push.schemas import (
    NOTIFICATION_TYPE_DAILY_DIGEST,
    PushMessage,
    PushResult,
)

logger = logging.getLogger(__name__)

NOTIFICATION_TITLE = "AI Daily 已更新"


@dataclass
class PushReport:
    """Outcome of one notification attempt, for logging and tests."""

    skipped_reason: str | None = None
    attempted: int = 0
    delivered: int = 0
    failed: int = 0
    disabled_tokens: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def skipped(self) -> bool:
        return self.skipped_reason is not None

    @property
    def sent(self) -> bool:
        return self.delivered > 0


def build_digest_body(news_count: int, github_count: int) -> str:
    """Compose the notification body, omitting the GitHub part when empty."""
    body = f"今日精选 {news_count} 条 AI 动态"
    if github_count > 0:
        body += f" · {github_count} 个 GitHub 项目"
    return body


def send_digest_notification(
    *,
    date: str,
    news_count: int,
    github_count: int,
    client: ExpoPushClient | None = None,
    force: bool = False,
) -> PushReport:
    """Notify registered devices about a freshly stored digest.

    Never raises: a failed notification must not turn a successful refresh into a
    failure. ``force`` is used by the development test endpoint.
    """
    if not push_enabled():
        return PushReport(skipped_reason="push disabled")

    session = new_session()
    try:
        devices = PushDeviceRepository(session).list_enabled()
        if not devices:
            return PushReport(skipped_reason="no enabled devices")

        digest_repository = DigestRepository(session)
        if not force and not digest_repository.needs_notification(date):
            return PushReport(skipped_reason="already notified")

        tokens = [device.expo_push_token for device in devices]
    finally:
        session.close()

    messages = [
        PushMessage(
            to=token,
            title=NOTIFICATION_TITLE,
            body=build_digest_body(news_count, github_count),
            data={"type": NOTIFICATION_TYPE_DAILY_DIGEST, "date": date},
            channel_id=notification_channel_id(),
        )
        for token in tokens
    ]

    push_client = client or ExpoPushClient()
    try:
        result = push_client.send(messages)
    except ExpoPushError as exc:
        logger.warning("digest push failed date=%s error=%s", date, exc)
        return PushReport(attempted=len(messages), error=str(exc))
    except Exception as exc:
        logger.exception("unexpected digest push failure date=%s", date)
        return PushReport(attempted=len(messages), error=str(exc))

    report = _apply_result(date, result, attempted=len(messages))
    logger.info(
        "digest push date=%s attempted=%s delivered=%s failed=%s disabled=%s",
        date,
        report.attempted,
        report.delivered,
        report.failed,
        len(report.disabled_tokens),
    )
    return report


def _apply_result(date: str, result: PushResult, *, attempted: int) -> PushReport:
    report = PushReport(
        attempted=attempted,
        delivered=result.delivered,
        failed=result.failed,
        disabled_tokens=result.stale_tokens,
    )
    if not result.stale_tokens and result.delivered == 0:
        return report

    session = new_session()
    try:
        device_repository = PushDeviceRepository(session)
        for token in result.stale_tokens:
            # Expo says this token can never work again; stop retrying it daily.
            device_repository.disable(token)
        if result.delivered > 0:
            DigestRepository(session).mark_notified(date)
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("could not persist push outcome date=%s", date)
    finally:
        session.close()
    return report
