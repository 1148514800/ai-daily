"""One-shot digest rebuild: issue windows, stored articles only, no RSS/LLM."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db.repositories import DigestRepository, GitHubRepository, NewsRepository
from app.db.session import new_session
from app.jobs.rebuild_digests import (
    articles_for_window,
    main,
    parse_dates,
    rebuild_dates,
)
from app.models import GitHubProject, NewsCategory, NewsItem
from app.services.digest_window import DigestWindow, historical_window

UTC = timezone.utc

# 08:00 Asia/Shanghai == 00:00 UTC, the default daily cutoff. CUTOFF_12 is the
# cutoff on 2026-09-12, so digest 2026-09-13 covers (CUTOFF_12, CUTOFF_13].
CUTOFF_11 = datetime(2026, 9, 11, 0, 0, tzinfo=UTC)
CUTOFF_12 = datetime(2026, 9, 12, 0, 0, tzinfo=UTC)
CUTOFF_13 = datetime(2026, 9, 13, 0, 0, tzinfo=UTC)
CUTOFF_14 = datetime(2026, 9, 14, 0, 0, tzinfo=UTC)


def inside(date: str) -> datetime:
    """The midpoint of a digest's historical window, comfortably inside it."""
    window = historical_window(date)
    return window.start + (window.end - window.start) / 2


def stored_news(news_id: str, published_at: datetime, *, source: str = "OpenAI") -> NewsItem:
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


def store_articles(items: list[NewsItem]) -> None:
    session = new_session()
    try:
        NewsRepository(session).upsert_many(items)
        session.commit()
    finally:
        session.close()


def save_digest(
    date: str,
    news_ids: list[str],
    *,
    github_ids: list[str] | None = None,
    window: DigestWindow | None = None,
) -> None:
    """Write a digest. Without an explicit window it records nothing, which is
    how a pre-window digest looks and forces the cutoff-derived fallback."""
    session = new_session()
    try:
        DigestRepository(session).save(
            date=date,
            title="今日 AI 日报",
            description="d",
            news_ids=news_ids,
            github_ids=github_ids or [],
            window_start=window.start if window else None,
            window_end=window.end if window else None,
        )
        session.commit()
    finally:
        session.close()


def stored_window(date: str) -> tuple[datetime | None, datetime | None]:
    session = new_session()
    try:
        return DigestRepository(session).get_window(date)
    finally:
        session.close()


def stored_ids(date: str) -> list[str]:
    session = new_session()
    try:
        return [item.id for item in DigestRepository(session).get_news(date)]
    finally:
        session.close()


def count_articles() -> int:
    session = new_session()
    try:
        return NewsRepository(session).count()
    finally:
        session.close()


def github_project(project_id: str) -> GitHubProject:
    return GitHubProject(
        id=project_id,
        repo="acme/repo",
        name="repo",
        description="desc",
        language="Python",
        stars=100,
        stars_delta=1,
        summary_cn="中文摘要",
        why_it_matters="",
        url="https://github.com/acme/repo",
        rank=1,
        forks=5,
        license="MIT",
        topics=["llm"],
    )


# --- argument parsing ---


def test_parse_dates_keeps_order_and_drops_duplicates() -> None:
    assert parse_dates(" 2026-09-13 , 2026-09-12 ,2026-09-13") == ["2026-09-13", "2026-09-12"]


BAD_DATE_INPUTS = ["", " , ", "2026-13-40", "12/09/2026", "2026-9-1"]


def test_parse_dates_rejects_bad_input() -> None:
    for raw in BAD_DATE_INPUTS:
        with pytest.raises(ValueError):
            parse_dates(raw)


def test_main_reports_bad_dates_without_touching_the_database(capsys) -> None:
    assert main(["--dates", "nope"]) == 2
    assert "invalid date" in capsys.readouterr().out


# --- window attribution ---


def test_historical_window_follows_the_configured_cutoff() -> None:
    window = historical_window("2026-09-13")
    # One day long: from the previous cutoff up to this date's cutoff.
    assert window.start == CUTOFF_12
    assert window.end == CUTOFF_13


def test_articles_for_window_selects_only_that_window() -> None:
    window = historical_window("2026-09-13")
    articles = [
        stored_news("start", window.start),
        stored_news("start+1s", window.start + timedelta(seconds=1)),
        stored_news("middle", inside("2026-09-13")),
        stored_news("end", window.end),
        stored_news("end+1s", window.end + timedelta(seconds=1)),
    ]
    # start is exclusive, end is inclusive, so the boundaries decide membership.
    assert [item.id for item in articles_for_window(articles, window)] == [
        "end",
        "middle",
        "start+1s",
    ]


def test_articles_for_window_ignores_unparseable_timestamps() -> None:
    broken = stored_news("broken", datetime(2026, 9, 13, 1, tzinfo=UTC)).model_copy(
        update={"published_at": "not-a-date"}
    )
    assert articles_for_window([broken], historical_window("2026-09-13")) == []


# --- rebuild behaviour ---


def test_rebuild_removes_a_future_article_from_a_digest() -> None:
    """A 09-14 article linked to 09-12/09-13 is outside both windows."""
    on_twelfth = stored_news("on-12", inside("2026-09-12"))
    future = stored_news("future", CUTOFF_14)
    store_articles([on_twelfth, future])
    save_digest("2026-09-12", ["future", "on-12"])
    save_digest("2026-09-13", ["future"])

    results = rebuild_dates(["2026-09-12", "2026-09-13"])
    by_date = {result.date: result for result in results}

    assert by_date["2026-09-12"].before == ["future", "on-12"]
    assert by_date["2026-09-12"].after == ["on-12"]
    assert by_date["2026-09-12"].removed == ["future"]
    assert by_date["2026-09-13"].before == ["future"]
    assert by_date["2026-09-13"].after == []
    assert by_date["2026-09-13"].removed == ["future"]

    assert stored_ids("2026-09-12") == ["on-12"]
    assert stored_ids("2026-09-13") == []


def test_rebuild_derives_the_window_from_the_configured_cutoff() -> None:
    """A digest without a stored window falls back to (cutoff(D-1), cutoff(D)]."""
    on_twelfth = stored_news("on-12", inside("2026-09-12"))
    store_articles([on_twelfth])
    save_digest("2026-09-12", ["on-12"])

    result = rebuild_dates(["2026-09-12"])[0]

    assert result.window == historical_window("2026-09-12")
    assert stored_window("2026-09-12") == (CUTOFF_11, CUTOFF_12)


def test_rebuild_keeps_a_digest_stored_window() -> None:
    """A digest built at a real refresh time keeps its own window."""
    on_twelfth = stored_news("on-12", datetime(2026, 9, 11, 20, 0, tzinfo=UTC))
    store_articles([on_twelfth])
    own = DigestWindow(start=datetime(2026, 9, 11, 18, 0, tzinfo=UTC), end=CUTOFF_12)
    save_digest("2026-09-12", ["on-12"], window=own)

    result = rebuild_dates(["2026-09-12"])[0]

    assert result.window == own
    assert stored_ids("2026-09-12") == ["on-12"]


def test_rebuild_does_not_delete_or_fetch_articles() -> None:
    on_twelfth = stored_news("on-12", inside("2026-09-12"))
    future = stored_news("future", CUTOFF_14)
    store_articles([on_twelfth, future])
    save_digest("2026-09-12", ["future", "on-12"])

    rebuild_dates(["2026-09-12"])

    # Original rows survive, including the rejected one.
    assert count_articles() == 2
    session = new_session()
    try:
        assert NewsRepository(session).get("future") is not None
    finally:
        session.close()


def test_rebuild_can_add_a_missing_article() -> None:
    window = historical_window("2026-09-12")
    first = stored_news("first", window.start + timedelta(hours=2))
    other = stored_news("other", window.start + timedelta(hours=8))
    store_articles([first, other])
    save_digest("2026-09-12", ["first"])

    result = rebuild_dates(["2026-09-12"])[0]

    assert result.added == ["other"]
    # Newest first, the same ordering a normal refresh produces.
    assert stored_ids("2026-09-12") == ["other", "first"]


def test_rebuild_keeps_github_links() -> None:
    on_twelfth = stored_news("on-12", inside("2026-09-12"))
    store_articles([on_twelfth])
    session = new_session()
    try:
        GitHubRepository(session).upsert_many([github_project("gh-0001")])
        session.commit()
    finally:
        session.close()
    save_digest("2026-09-12", ["on-12"], github_ids=["gh-0001"])

    rebuild_dates(["2026-09-12"])

    session = new_session()
    try:
        assert DigestRepository(session).get_github_ids("2026-09-12") == ["gh-0001"]
    finally:
        session.close()


def test_rebuild_of_a_day_with_no_articles_clears_links() -> None:
    future = stored_news("future", CUTOFF_14)
    store_articles([future])
    save_digest("2026-09-13", ["future"])

    rebuild_dates(["2026-09-13"])

    assert stored_ids("2026-09-13") == []


def test_rebuild_is_idempotent() -> None:
    on_twelfth = stored_news("on-12", inside("2026-09-12"))
    store_articles([on_twelfth])
    save_digest("2026-09-12", ["on-12"])

    rebuild_dates(["2026-09-12"])
    second = rebuild_dates(["2026-09-12"])[0]

    assert second.removed == []
    assert second.added == []
    assert stored_ids("2026-09-12") == ["on-12"]


def test_main_reports_the_diff(capsys) -> None:
    on_twelfth = stored_news("on-12", inside("2026-09-12"))
    future = stored_news("future", CUTOFF_14)
    store_articles([on_twelfth, future])
    save_digest("2026-09-12", ["future", "on-12"])

    assert main(["--dates", "2026-09-12"]) == 0

    output = capsys.readouterr().out
    assert "2026-09-12: 2 -> 1" in output
    assert "removed: future" in output
    assert "kept: on-12" in output
