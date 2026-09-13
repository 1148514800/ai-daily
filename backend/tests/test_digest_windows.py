"""Issue windows: (window_start, window_end] decides digest membership.

A digest is no longer a calendar-day report. It covers everything published
since the previous successful cutoff, so an article belongs to exactly the one
window that contains it and future timestamps stay out.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.collectors.raw import RawArticle
from app.config.sources import source_map
from app.config.timezone import app_timezone
from app.models import NewsCategory, NewsItem
from app.services.digest_store import DigestStore, store
from app.services.digest_window import (
    DigestWindow,
    continuing_window,
    first_window,
    is_future,
    resolve_window,
    scheduled_cutoff,
)
from tests.conftest import EMPTY_HTML, EMPTY_RSS, build_rss

UTC = timezone.utc

# 2026-09-13 08:00 in Asia/Shanghai, the default daily cutoff.
CUTOFF_13 = datetime(2026, 9, 12, 0, 0, tzinfo=UTC)
CUTOFF_14 = datetime(2026, 9, 13, 0, 0, tzinfo=UTC)


def shanghai(local_date: str, hour: int = 0, minute: int = 0, second: int = 0) -> datetime:
    """The UTC instant for a wall-clock time in Asia/Shanghai."""
    local = datetime.strptime(local_date, "%Y-%m-%d").replace(
        hour=hour, minute=minute, second=second, tzinfo=app_timezone()
    )
    return local.astimezone(UTC)


def raw_article(*, title: str, slug: str, published_at: datetime | None) -> RawArticle:
    url = f"https://openai.com/index/{slug}"
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


def news_item(*, news_id: str, published_at: datetime, source: str = "OpenAI") -> NewsItem:
    return NewsItem(
        id=news_id,
        title_cn=f"标题 {news_id}",
        title_original=f"Title {news_id}",
        summary="",
        why_it_matters="",
        source=source,
        source_type="official",
        published_at=published_at.isoformat(),
        category=NewsCategory.highlight,
        tags=[source],
        url=f"https://openai.com/index/{news_id}",
    )


def per_source_fetch(items: list[tuple[str, str, datetime]]):
    """Serve one feed per enabled source, each with its own URL namespace.

    The RSS sources carry the articles under test. The HTML sources answer with
    an empty listing of their own shape, so they neither fail the refresh nor
    contribute news the window tests did not ask for.
    """
    sources = source_map()

    def fetch(url: str, timeout: float = 10.0) -> str:
        for source_id, source in sources.items():
            if source.url.rstrip("/") == url.rstrip("/"):
                break
        else:
            if url.startswith("https://api-docs.deepseek.com/"):
                return EMPTY_HTML["deepseek"]
            raise AssertionError(f"unexpected source {url}")
        if source.kind == "html":
            return EMPTY_HTML.get(source_id, EMPTY_RSS)
        entries = [
            (title, f"https://example.com/{source_id}/{slug}", when)
            for title, slug, when in items
        ]
        return build_rss(entries)

    return fetch


def ids_for(date: str) -> list[str]:
    return [item.id for item in store.get_digest(date).news]


def titles_for(date: str) -> set[str]:
    return {item.title_original for item in store.get_digest(date).news}


# --- the membership rule ---


def test_window_boundaries() -> None:
    """start -> reject, start+1s -> accept, middle/end -> accept, end+1s -> reject."""
    start = shanghai("2026-09-12", 8)
    end = shanghai("2026-09-13", 8)
    window = DigestWindow(start=start, end=end)

    assert window.contains(start) is False
    assert window.contains(start + timedelta(seconds=1)) is True
    assert window.contains(start + timedelta(hours=12)) is True
    assert window.contains(end) is True
    assert window.contains(end + timedelta(seconds=1)) is False


def test_window_rejects_nothing_without_a_timestamp() -> None:
    window = DigestWindow(start=CUTOFF_13, end=CUTOFF_14)
    assert window.contains(None) is False
    assert window.contains("not-a-date") is False


def test_window_accepts_iso_strings() -> None:
    window = DigestWindow(start=CUTOFF_13, end=CUTOFF_14)
    assert window.contains(CUTOFF_14.isoformat()) is True
    assert window.contains(CUTOFF_13.isoformat()) is False


def test_adjacent_windows_do_not_overlap() -> None:
    first = DigestWindow(start=CUTOFF_13, end=CUTOFF_14)
    second = DigestWindow(start=CUTOFF_14, end=CUTOFF_14 + timedelta(days=1))
    boundary = CUTOFF_14

    # start is exclusive, so the shared boundary stays with the earlier window
    # and the two windows still share no instant.
    assert first.contains(boundary) is True
    assert second.contains(boundary) is False
    for moment in (boundary - timedelta(seconds=1), boundary, boundary + timedelta(seconds=1)):
        assert not (first.contains(moment) and second.contains(moment))


# --- future article ---


def test_future_article_is_rejected() -> None:
    """now 2026-09-13 10:00, published 2026-09-14 08:00 -> reject."""
    now = shanghai("2026-09-13", 10)
    published = shanghai("2026-09-14", 8)
    window = DigestWindow(start=shanghai("2026-09-12", 8), end=now)

    assert window.contains(published) is False
    assert is_future(published, now) is True


def test_future_article_is_not_persisted() -> None:
    now = shanghai("2026-09-13", 10)
    fetch = per_source_fetch(
        [
            ("Today story", "today", now - timedelta(hours=2)),
            ("Tomorrow story", "tomorrow", shanghai("2026-09-14", 8)),
        ]
    )

    DigestStore().refresh(now=now, fetch_text=fetch)

    assert titles_for("2026-09-13") == {"Today story"}


def test_future_window_end_never_exceeds_now() -> None:
    now = shanghai("2026-09-13", 10)
    assert first_window(now).end == now
    assert continuing_window(CUTOFF_13, now).end == now


# --- window derivation ---


def test_first_digest_uses_the_previous_24_hours() -> None:
    now = shanghai("2026-09-13", 8)
    window = resolve_window(now=now)

    assert window.start == now - timedelta(hours=24)
    assert window.end == now


def test_new_digest_continues_from_the_previous_cutoff() -> None:
    now = shanghai("2026-09-14", 8)
    window = resolve_window(now=now, previous_end=CUTOFF_14)

    assert window.start == CUTOFF_14
    assert window.end == now


def test_existing_window_start_wins_over_the_previous_cutoff() -> None:
    """A second refresh the same day keeps extending its own window."""
    existing_start = shanghai("2026-09-13", 8)
    now = shanghai("2026-09-13", 18)
    window = resolve_window(now=now, existing_start=existing_start, previous_end=CUTOFF_14)

    assert window.start == existing_start
    assert window.end == now


def test_stale_cutoff_falls_back_to_the_default_lookback() -> None:
    """An inverted window must never be used, e.g. a future cutoff."""
    now = shanghai("2026-09-13", 8)
    window = resolve_window(now=now, previous_end=now + timedelta(hours=1))

    assert window.start == now - timedelta(hours=24)
    assert window.end == now


def test_scheduled_cutoff_uses_the_configured_hour() -> None:
    # 08:00 Asia/Shanghai is 00:00 UTC.
    assert scheduled_cutoff("2026-09-13") == CUTOFF_13 + timedelta(days=1)
    assert scheduled_cutoff("2026-09-13") == datetime(2026, 9, 13, 0, 0, tzinfo=UTC)


# --- refresh behaviour ---


def test_previous_day_evening_news_enters_todays_digest() -> None:
    """09-12 20:00 and 09-13 00:00 both belong to the 09-13 08:00 digest."""
    now = shanghai("2026-09-13", 8)
    fetch = per_source_fetch(
        [
            ("Evening on the twelfth", "evening-12", shanghai("2026-09-12", 20)),
            ("Midnight on the thirteenth", "midnight-13", shanghai("2026-09-13", 0)),
        ]
    )

    DigestStore().refresh(now=now, fetch_text=fetch)

    assert titles_for("2026-09-13") == {"Evening on the twelfth", "Midnight on the thirteenth"}


def test_cutoff_minute_is_included_and_the_second_after_is_not() -> None:
    now = shanghai("2026-09-13", 8)
    fetch = per_source_fetch(
        [
            ("Exactly at the cutoff", "at-cutoff", now),
            ("One second after the cutoff", "after-cutoff", now + timedelta(seconds=1)),
        ]
    )

    DigestStore().refresh(now=now, fetch_text=fetch)

    assert titles_for("2026-09-13") == {"Exactly at the cutoff"}


def test_missed_day_continues_the_window_instead_of_a_fixed_24h() -> None:
    """A day with no run must not lose the news published during it."""
    day_one = shanghai("2026-09-13", 8)
    day_three = shanghai("2026-09-15", 8)  # 09-14 was missed entirely
    first_fetch = per_source_fetch([("On the thirteenth", "d13", shanghai("2026-09-13", 9))])
    later_fetch = per_source_fetch([("On the fourteenth", "d14", shanghai("2026-09-14", 12))])

    DigestStore().refresh(now=day_one, fetch_text=first_fetch)
    DigestStore().refresh(now=day_three, fetch_text=later_fetch)

    digest = store.get_digest("2026-09-15")
    assert digest.window_start is not None
    window = DigestWindow(
        start=datetime.fromisoformat(digest.window_start),
        end=datetime.fromisoformat(digest.window_end),
    )
    # The window spans the missed day rather than only the last 24h.
    assert window.start == day_one
    assert window.end == day_three
    assert titles_for("2026-09-15") == {"On the fourteenth"}


def test_same_day_second_refresh_merges_instead_of_replacing() -> None:
    """08:00 gives A B, 18:00 gives C D, the digest ends up with A B C D."""
    morning = shanghai("2026-09-13", 8)
    evening = shanghai("2026-09-13", 18)
    morning_fetch = per_source_fetch(
        [("Story A", "a", shanghai("2026-09-13", 7)), ("Story B", "b", shanghai("2026-09-13", 7, 30))]
    )
    evening_fetch = per_source_fetch(
        [("Story C", "c", shanghai("2026-09-13", 12)), ("Story D", "d", shanghai("2026-09-13", 17))]
    )

    DigestStore().refresh(now=morning, fetch_text=morning_fetch)
    DigestStore().refresh(now=evening, fetch_text=evening_fetch)

    assert len(store.list_digest_summaries()) == 1
    assert titles_for("2026-09-13") == {"Story A", "Story B", "Story C", "Story D"}


def test_second_refresh_keeps_window_start_and_moves_window_end() -> None:
    morning = shanghai("2026-09-13", 8)
    evening = shanghai("2026-09-13", 18)
    fetch = per_source_fetch([("Story A", "a", shanghai("2026-09-13", 7))])

    DigestStore().refresh(now=morning, fetch_text=fetch)
    first_start = store.get_digest("2026-09-13").window_start

    later_fetch = per_source_fetch([("Story C", "c", shanghai("2026-09-13", 12))])
    DigestStore().refresh(now=evening, fetch_text=later_fetch)

    digest = store.get_digest("2026-09-13")
    assert digest.window_start == first_start
    assert digest.window_end == evening.isoformat()


def test_repeated_refresh_does_not_duplicate_links() -> None:
    moment = shanghai("2026-09-13", 8)
    fetch = per_source_fetch(
        [("Story A", "a", shanghai("2026-09-13", 7)), ("Story B", "b", shanghai("2026-09-13", 7, 30))]
    )

    DigestStore().refresh(now=moment, fetch_text=fetch)
    DigestStore().refresh(now=moment + timedelta(minutes=1), fetch_text=fetch)
    DigestStore().refresh(now=moment + timedelta(minutes=2), fetch_text=fetch)

    news_ids = ids_for("2026-09-13")
    assert len(news_ids) == 2
    assert len(set(news_ids)) == 2


def test_adjacent_digests_share_no_news() -> None:
    """Consecutive windows are disjoint, so their news_ids cannot intersect."""
    day_one = shanghai("2026-09-13", 8)
    day_two = shanghai("2026-09-14", 8)
    day_one_fetch = per_source_fetch(
        [
            ("Morning story", "m1", shanghai("2026-09-13", 7)),
            ("Evening story", "e1", shanghai("2026-09-13", 20)),
        ]
    )
    day_two_fetch = per_source_fetch([("Next day story", "n2", shanghai("2026-09-14", 7))])

    DigestStore().refresh(now=day_one, fetch_text=day_one_fetch)
    DigestStore().refresh(now=day_two, fetch_text=day_two_fetch)

    first = set(ids_for("2026-09-13"))
    second = set(ids_for("2026-09-14"))
    assert first
    assert second
    assert first & second == set()


def test_boundary_article_belongs_only_to_the_later_digest() -> None:
    """An article exactly at the cutoff goes to the new digest, not the old."""
    day_one = shanghai("2026-09-13", 8)
    day_two = shanghai("2026-09-14", 8)
    boundary = day_two  # exactly the second digest's window_end
    day_one_fetch = per_source_fetch([("At the boundary", "boundary", boundary)])
    day_two_fetch = per_source_fetch([("At the boundary", "boundary", boundary)])

    DigestStore().refresh(now=day_one, fetch_text=day_one_fetch)
    DigestStore().refresh(now=day_two, fetch_text=day_two_fetch)

    assert ids_for("2026-09-13") == []
    assert len(ids_for("2026-09-14")) == 1


def test_missing_published_at_is_not_a_candidate() -> None:
    now = shanghai("2026-09-13", 10)
    article = raw_article(title="No date", slug="no-date", published_at=None)
    window = DigestWindow(start=shanghai("2026-09-12", 8), end=now)
    assert window.contains(article.published_at) is False


# --- persist-level defence ---


def test_persist_refuses_news_outside_the_window() -> None:
    window = DigestWindow(start=CUTOFF_13, end=CUTOFF_14)
    inside = news_item(news_id="inside", published_at=CUTOFF_14)
    before = news_item(news_id="before", published_at=CUTOFF_13)
    after = news_item(news_id="after", published_at=CUTOFF_14 + timedelta(seconds=1))

    store.persist(
        date="2026-09-13",
        window=window,
        news_items=[inside, before, after],
        github_projects=[],
    )

    assert ids_for("2026-09-13") == ["inside"]


def test_persist_refuses_future_news() -> None:
    now = shanghai("2026-09-13", 10)
    window = DigestWindow(start=shanghai("2026-09-12", 10), end=now)
    future = news_item(news_id="future", published_at=shanghai("2026-09-14", 8))

    store.persist(
        date="2026-09-13",
        window=window,
        news_items=[news_item(news_id="today", published_at=now), future],
        github_projects=[],
    )

    assert ids_for("2026-09-13") == ["today"]


def test_rejected_news_is_still_stored() -> None:
    """Window rejection must not delete the article row."""
    window = DigestWindow(start=CUTOFF_13, end=CUTOFF_14)
    outside = news_item(news_id="kept-row", published_at=CUTOFF_14 + timedelta(hours=5))

    store.persist(date="2026-09-13", window=window, news_items=[outside], github_projects=[])

    assert store.get_news("kept-row") is not None


def test_persist_records_the_window() -> None:
    window = DigestWindow(start=CUTOFF_13, end=CUTOFF_14)
    store.persist(
        date="2026-09-13",
        window=window,
        news_items=[news_item(news_id="inside", published_at=CUTOFF_14)],
        github_projects=[],
    )

    digest = store.get_digest("2026-09-13")
    assert digest.window_start == CUTOFF_13.isoformat()
    assert digest.window_end == CUTOFF_14.isoformat()


def test_digest_description_covers_merged_content() -> None:
    """An extended digest still describes everything it links."""
    morning = shanghai("2026-09-13", 8)
    evening = shanghai("2026-09-13", 18)
    morning_fetch = per_source_fetch([("Story A", "a", shanghai("2026-09-13", 7))])
    evening_fetch = per_source_fetch([("Story C", "c", shanghai("2026-09-13", 12))])

    DigestStore().refresh(now=morning, fetch_text=morning_fetch)
    DigestStore().refresh(now=evening, fetch_text=evening_fetch)

    digest = store.get_digest("2026-09-13")
    assert len(digest.news) == 2
    # The description counts the merged content, not just the last run.
    assert "2 条更新" in digest.description


def test_real_world_rows_no_longer_split_by_local_day() -> None:
    """2026-09-11 16:00 UTC is local midnight; both rows share one window."""
    midnight_row = datetime(2026, 9, 11, 16, 0, tzinfo=UTC)
    earlier_row = datetime(2026, 9, 11, 10, 0, tzinfo=UTC)
    window = DigestWindow(start=shanghai("2026-09-11", 8), end=shanghai("2026-09-12", 8))

    assert window.contains(midnight_row) is True
    assert window.contains(earlier_row) is True

    future_row = datetime(2026, 9, 14, 0, 0, tzinfo=UTC)
    assert window.contains(future_row) is False
