from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from app.config.timezone import digest_date_for
from app.services.digest_store import store
from app.services.github_store import GitHubRefreshStats, github_store

logger = logging.getLogger(__name__)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class CombinedRefresh:
    date: str
    reports: list
    github_stats: GitHubRefreshStats
    saved: bool
    window_start: datetime
    window_end: datetime


def refresh_all(
    *,
    now: datetime | None = None,
    fetch_text=None,
    fetch_trending=None,
    github_client=None,
    enrich=None,
) -> CombinedRefresh:
    """Collect news and GitHub projects, then persist one digest atomically.

    Both sources are collected first so a single digest write can link them.
    """
    current = now or now_utc()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    date = digest_date_for(current)
    window = store.resolve_window(date, current)

    news_items, reports = store.collect_news(window, current, fetch_text)
    github_stats = github_store.refresh(
        fetch_text=fetch_trending,
        github_client=github_client,
        enrich=enrich,
    )

    saved = store.persist(
        date=date,
        window=window,
        news_items=news_items,
        github_projects=github_store.list_projects(),
    )
    return CombinedRefresh(
        date=date,
        reports=reports,
        github_stats=github_stats,
        saved=saved,
        window_start=window.start,
        window_end=window.end,
    )
