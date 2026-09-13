"""Digest date ownership: rolling window, future timestamps, and local days.

The daily digest is a calendar-day report, so every article belongs to exactly
one APP_TIMEZONE day. A rolling 24h window must never leak a neighbouring day's
article (or a future one) into the digest being written.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.collectors.rss import (
    article_within_last_hours,
    belongs_to_digest_date,
    collect_all_sources,
)
from app.collectors.raw import RawArticle
from app.config.sources import source_map
from app.config.timezone import digest_date_for, digest_date_for_iso
from app.models import NewsCategory, NewsItem
from app.services.digest_store import DigestStore, store
from tests.conftest import build_rss

UTC = timezone.utc


def shanghai(local_date: str, hour: int = 0, minute: int = 0, second: int = 0) -> datetime:
    """The UTC instant for a wall-clock time in Asia/Shanghai."""
    from app.config.timezone import app_timezone

    local = datetime.strptime(local_date, "%Y-%m-%d").replace(
        hour=hour, minute=minute, second=second, tzinfo=app_timezone()
    )
    return local.astimezone(UTC)


def raw_article(*, title: str, url: str, published_at: datetime | None) -> RawArticle:
    return RawArticle(
        source_id="openai",
        source="OpenAI",
        source_type="official",
        title=title,
        url=url,
        canonical_url=url,
        published_at=published_at,
        summary="",
    )


def news_item(*, news_id: str, published_at: datetime) -> NewsItem:
    return NewsItem(
        id=news_id,
        title_cn=f"标题 {news_id}",
        title_original=f"Title {news_id}",
        summary="",
        why_it_matters="",
        source="OpenAI",
        source_type="official",
        published_at=published_at.isoformat(),
        category=NewsCategory.highlight,
        tags=["OpenAI"],
        url=f"https://openai.com/index/{news_id}",
    )


def per_source_fetch(items: list[tuple[str, datetime]]):
    """Serve one feed per enabled source, each with its own URL namespace."""
    sources = source_map()

    def fetch(url: str, timeout: float = 10.0) -> str:
        for source_id, source in sources.items():
            if source.url == url:
                break
        else:
            raise AssertionError(f"unexpected source {url}")
        entries = [
            (title, f"https://example.com/{source_id}/{slug}", when)
            for title, slug, when in items
        ]
        return build_rss(entries)

    return fetch


def ids_for(date: str) -> set[str]:
    return {item.id for item in store.get_digest(date).news}


# --- date derivation ---


def test_local_date_conversion_uses_app_timezone() -> None:
    assert digest_date_for(shanghai("2026-09-12", 23, 59, 59)) == "2026-09-12"
    assert digest_date_for(shanghai("2026-09-13", 0, 0, 0)) == "2026-09-13"


def test_midnight_is_the_first_instant_of_its_day() -> None:
    """One second apart, opposite sides of the local day boundary."""
    last_second = shanghai("2026-09-12", 23, 59, 59)
    first_second = shanghai("2026-09-13", 0, 0, 0)
    assert first_second - last_second == timedelta(seconds=1)
    assert digest_date_for_iso(last_second.isoformat()) == "2026-09-12"
    assert digest_date_for_iso(first_second.isoformat()) == "2026-09-13"


def test_naive_timestamps_are_read_as_utc() -> None:
    # Stored published_at values are UTC and may come back naive.
    assert digest_date_for_iso("2026-09-11T16:00:00") == "2026-09-12"
    assert digest_date_for_iso("2026-09-11T15:59:59") == "2026-09-11"


def test_unparseable_timestamp_belongs_to_no_day() -> None:
    assert digest_date_for_iso("") is None
    assert digest_date_for_iso("not-a-date") is None
    assert belongs_to_digest_date(None, "2026-09-12") is False


# --- future timestamp bug ---


def test_future_article_is_rejected() -> None:
    """now 2026-09-13 10:00, published 2026-09-14 08:00 -> reject."""
    now = shanghai("2026-09-13", 10)
    published = shanghai("2026-09-14", 8)
    article = raw_article(
        title="Tomorrow's announcement",
        url="https://openai.com/index/tomorrow",
        published_at=published,
    )

    assert article_within_last_hours(article, now) is False
    # It is a different day as well, so it can never be owned by 09-13.
    assert belongs_to_digest_date(published, "2026-09-13") is False


def test_future_article_never_enters_candidates() -> None:
    now = shanghai("2026-09-13", 10)
    fetch = per_source_fetch(
        [
            ("Today story", "today", now - timedelta(hours=2)),
            ("Tomorrow story", "tomorrow", shanghai("2026-09-14", 8)),
        ]
    )

    reports = collect_all_sources(fetch_text=fetch)
    recent = [
        article
        for report in reports
        for article in report.valid
        if article_within_last_hours(article, now)
    ]
    titles = {article.title for article in recent}
    assert titles == {"Today story"}


def test_future_article_is_not_persisted() -> None:
    """Even if a collector handed it over, the digest must not link it."""
    now = shanghai("2026-09-13", 10)
    fetch = per_source_fetch(
        [
            ("Today story", "today", now - timedelta(hours=2)),
            ("Tomorrow story", "tomorrow", shanghai("2026-09-14", 8)),
        ]
    )

    DigestStore().refresh(now=now, fetch_text=fetch)

    digest = store.get_digest("2026-09-13")
    titles = {item.title_original for item in digest.news}
    assert titles == {"Today story"}


def test_window_accepts_only_the_last_24_hours() -> None:
    now = shanghai("2026-09-13", 10)
    inside = raw_article(
        title="Inside",
        url="https://openai.com/index/inside",
        published_at=now - timedelta(hours=23, minutes=59),
    )
    exactly_24h = raw_article(
        title="Edge",
        url="https://openai.com/index/edge",
        published_at=now - timedelta(hours=24),
    )
    outside = raw_article(
        title="Outside",
        url="https://openai.com/index/outside",
        published_at=now - timedelta(hours=24, seconds=1),
    )
    future = raw_article(
        title="Future",
        url="https://openai.com/index/future",
        published_at=now + timedelta(seconds=1),
    )

    assert article_within_last_hours(inside, now) is True
    assert article_within_last_hours(exactly_24h, now) is True
    assert article_within_last_hours(outside, now) is False
    assert article_within_last_hours(future, now) is False


def test_missing_published_at_is_not_a_candidate() -> None:
    now = shanghai("2026-09-13", 10)
    article = raw_article(title="No date", url="https://openai.com/index/no-date", published_at=None)
    assert article_within_last_hours(article, now) is False


# --- cross-midnight ownership ---


def test_cross_midnight_articles_do_not_mix_days() -> None:
    """The 13th's digest cannot contain the 12th's 23:59 article."""
    late = shanghai("2026-09-12", 23, 59, 59)
    midnight = shanghai("2026-09-13", 0, 0, 0)
    assert belongs_to_digest_date(late, "2026-09-12") is True
    assert belongs_to_digest_date(late, "2026-09-13") is False
    assert belongs_to_digest_date(midnight, "2026-09-13") is True
    assert belongs_to_digest_date(midnight, "2026-09-12") is False


def test_twelfth_digest_excludes_thirteenth_midnight_news() -> None:
    """Refresh late on the 12th while the feed already carries the 13th."""
    now = shanghai("2026-09-12", 23, 59, 59)
    fetch = per_source_fetch(
        [
            ("Late on the twelfth", "late-12", shanghai("2026-09-12", 23, 0, 0)),
            ("First minute of the thirteenth", "early-13", shanghai("2026-09-13", 0, 0, 0)),
        ]
    )

    DigestStore().refresh(now=now, fetch_text=fetch)

    titles = {item.title_original for item in store.get_digest("2026-09-12").news}
    assert titles == {"Late on the twelfth"}


def test_thirteenth_digest_excludes_twelfth_late_news() -> None:
    """One second later the 12th's last article is 1s old but still not ours."""
    now = shanghai("2026-09-13", 0, 0, 1)
    fetch = per_source_fetch(
        [
            ("Late on the twelfth", "late-12", shanghai("2026-09-12", 23, 59, 59)),
            ("First minute of the thirteenth", "early-13", shanghai("2026-09-13", 0, 0, 0)),
        ]
    )

    DigestStore().refresh(now=now, fetch_text=fetch)

    titles = {item.title_original for item in store.get_digest("2026-09-13").news}
    assert titles == {"First minute of the thirteenth"}


# --- write-time defence ---


def test_persist_refuses_news_from_another_day() -> None:
    """A direct persist() call cannot create a cross-day link."""
    on_date = news_item(news_id="on-date", published_at=shanghai("2026-09-12", 8))
    off_date = news_item(news_id="off-date", published_at=shanghai("2026-09-11", 23, 59, 59))

    store.persist(date="2026-09-12", news_items=[on_date, off_date], github_projects=[])

    assert ids_for("2026-09-12") == {on_date.id}


def test_persist_refuses_future_news() -> None:
    future = news_item(news_id="future", published_at=shanghai("2026-09-13", 8))

    store.persist(
        date="2026-09-12",
        news_items=[news_item(news_id="today", published_at=shanghai("2026-09-12", 8)), future],
        github_projects=[],
    )

    assert ids_for("2026-09-12") == {"today"}


def test_rejected_news_is_not_deleted_from_storage() -> None:
    """The article row is still kept; only the wrong link is refused."""
    off_date = news_item(news_id="kept-row", published_at=shanghai("2026-09-11", 10))
    store.persist(date="2026-09-12", news_items=[off_date], github_projects=[])

    assert store.get_news("kept-row") is not None


# --- the real database scenario ---


def test_real_world_boundary_rows() -> None:
    """2026-09-11 16:00 UTC is local midnight, so it belongs to 09-12 only."""
    row = datetime(2026, 9, 11, 16, 0, tzinfo=UTC)
    assert digest_date_for(row) == "2026-09-12"
    assert belongs_to_digest_date(row, "2026-09-12") is True
    assert belongs_to_digest_date(row, "2026-09-11") is False
    assert belongs_to_digest_date(row, "2026-09-13") is False

    future = datetime(2026, 9, 14, 0, 0, tzinfo=UTC)
    assert digest_date_for(future) == "2026-09-14"
    for now in (shanghai("2026-09-12", 12), shanghai("2026-09-13", 12)):
        assert article_within_last_hours(
            raw_article(title="f", url="https://openai.com/index/f", published_at=future),
            now,
        ) is False
        assert belongs_to_digest_date(future, digest_date_for(now)) is False


def test_real_rows_produce_the_expected_digests() -> None:
    """Replay the three stored articles against 09-12 and 09-13."""
    midnight_row = news_item(
        news_id="midnight-row",
        published_at=datetime(2026, 9, 11, 16, 0, tzinfo=UTC),
    )
    earlier_row = news_item(
        news_id="earlier-row",
        published_at=datetime(2026, 9, 11, 10, 0, tzinfo=UTC),
    )
    future_row = news_item(
        news_id="future-row",
        published_at=datetime(2026, 9, 14, 0, 0, tzinfo=UTC),
    )

    # A 09-12 refresh may only keep the midnight row.
    fetch = per_source_fetch(
        [
            ("Midnight row", "midnight", datetime(2026, 9, 11, 16, 0, tzinfo=UTC)),
            ("Earlier row", "earlier", datetime(2026, 9, 11, 10, 0, tzinfo=UTC)),
            ("Future row", "future", datetime(2026, 9, 14, 0, 0, tzinfo=UTC)),
        ]
    )
    DigestStore().refresh(now=shanghai("2026-09-12", 12), fetch_text=fetch)
    assert store.get_digest("2026-09-12").news  # the midnight row landed

    store.persist(date="2026-09-12", news_items=[midnight_row], github_projects=[])
    assert ids_for("2026-09-12") == {"midnight-row"}

    store.persist(date="2026-09-13", news_items=[earlier_row, future_row], github_projects=[])
    assert store.get_digest("2026-09-13").news == []


# --- repository guard for the API surface ---


def test_get_digest_reports_only_its_own_day() -> None:
    on_date = news_item(news_id="solo", published_at=shanghai("2026-09-13", 9))
    store.persist(date="2026-09-13", news_items=[on_date], github_projects=[])
    store.persist(
        date="2026-09-12",
        news_items=[news_item(news_id="other", published_at=shanghai("2026-09-12", 9))],
        github_projects=[],
    )

    assert ids_for("2026-09-13") == {"solo"}
    assert ids_for("2026-09-12") == {"other"}
    assert ids_for("2026-09-13") & ids_for("2026-09-12") == set()


@pytest.mark.parametrize("hour", [0, 1, 12, 23])
def test_every_hour_of_the_day_belongs_to_its_local_date(hour: int) -> None:
    moment = shanghai("2026-09-13", hour, 30)
    assert digest_date_for(moment) == "2026-09-13"
    assert belongs_to_digest_date(moment, "2026-09-13") is True
