"""One-shot digest rebuild: stored articles only, no RSS and no LLM."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.db.repositories import DigestRepository, GitHubRepository, NewsRepository
from app.db.session import new_session
from app.jobs.rebuild_digests import articles_for_date, main, parse_dates, rebuild_dates
from app.models import GitHubProject, NewsCategory, NewsItem

UTC = timezone.utc


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


def save_digest(date: str, news_ids: list[str], *, github_ids: list[str] | None = None) -> None:
    session = new_session()
    try:
        DigestRepository(session).save(
            date=date,
            title="今日 AI 日报",
            description="d",
            news_ids=news_ids,
            github_ids=github_ids or [],
        )
        session.commit()
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


# --- date attribution ---


def test_articles_for_date_selects_only_the_local_day() -> None:
    articles = [
        stored_news("a", datetime(2026, 9, 11, 15, 59, 59, tzinfo=UTC)),
        stored_news("b", datetime(2026, 9, 11, 16, 0, tzinfo=UTC)),
        stored_news("c", datetime(2026, 9, 12, 15, 59, 59, tzinfo=UTC)),
        stored_news("d", datetime(2026, 9, 14, 0, 0, tzinfo=UTC)),
    ]

    assert [item.id for item in articles_for_date(articles, "2026-09-11")] == ["a"]
    # Newest first, the same ordering a normal refresh produces.
    assert [item.id for item in articles_for_date(articles, "2026-09-12")] == ["c", "b"]
    assert [item.id for item in articles_for_date(articles, "2026-09-13")] == []


def test_articles_for_date_ignores_unparseable_timestamps() -> None:
    broken = stored_news("broken", datetime(2026, 9, 12, 1, tzinfo=UTC)).model_copy(
        update={"published_at": "not-a-date"}
    )
    assert articles_for_date([broken], "2026-09-12") == []


# --- rebuild behaviour ---


def test_rebuild_removes_a_future_article_from_a_digest() -> None:
    """The stored bug: a 09-14 article was linked to 09-12 and 09-13."""
    midnight = stored_news("midnight", datetime(2026, 9, 11, 16, 0, tzinfo=UTC))
    earlier = stored_news("earlier", datetime(2026, 9, 11, 10, 0, tzinfo=UTC))
    future = stored_news("future", datetime(2026, 9, 14, 0, 0, tzinfo=UTC))
    store_articles([midnight, earlier, future])
    save_digest("2026-09-12", ["future", "midnight"])
    save_digest("2026-09-13", ["future"])

    results = rebuild_dates(["2026-09-12", "2026-09-13"])
    by_date = {result.date: result for result in results}

    assert by_date["2026-09-12"].before == ["future", "midnight"]
    assert by_date["2026-09-12"].after == ["midnight"]
    assert by_date["2026-09-12"].removed == ["future"]
    assert by_date["2026-09-13"].before == ["future"]
    assert by_date["2026-09-13"].after == []
    assert by_date["2026-09-13"].removed == ["future"]

    assert stored_ids("2026-09-12") == ["midnight"]
    assert stored_ids("2026-09-13") == []


def test_rebuild_does_not_delete_or_fetch_articles() -> None:
    midnight = stored_news("midnight", datetime(2026, 9, 11, 16, 0, tzinfo=UTC))
    future = stored_news("future", datetime(2026, 9, 14, 0, 0, tzinfo=UTC))
    store_articles([midnight, future])
    save_digest("2026-09-12", ["future", "midnight"])

    rebuild_dates(["2026-09-12"])

    # Original rows survive, including the rejected one.
    assert count_articles() == 2
    session = new_session()
    try:
        assert NewsRepository(session).get("future") is not None
    finally:
        session.close()


def test_rebuild_can_add_a_missing_article() -> None:
    midnight = stored_news("midnight", datetime(2026, 9, 11, 16, 0, tzinfo=UTC))
    other = stored_news("other", datetime(2026, 9, 12, 2, 0, tzinfo=UTC))
    store_articles([midnight, other])
    save_digest("2026-09-12", ["midnight"])

    result = rebuild_dates(["2026-09-12"])[0]

    assert result.added == ["other"]
    # Newest first, the same ordering a normal refresh produces.
    assert stored_ids("2026-09-12") == ["other", "midnight"]


def test_rebuild_keeps_github_links() -> None:
    midnight = stored_news("midnight", datetime(2026, 9, 11, 16, 0, tzinfo=UTC))
    store_articles([midnight])
    session = new_session()
    try:
        GitHubRepository(session).upsert_many([github_project("gh-0001")])
        session.commit()
    finally:
        session.close()
    save_digest("2026-09-12", ["midnight"], github_ids=["gh-0001"])

    rebuild_dates(["2026-09-12"])

    session = new_session()
    try:
        assert DigestRepository(session).get_github_ids("2026-09-12") == ["gh-0001"]
    finally:
        session.close()


def test_rebuild_of_a_day_with_no_articles_clears_links() -> None:
    future = stored_news("future", datetime(2026, 9, 14, 0, 0, tzinfo=UTC))
    store_articles([future])
    save_digest("2026-09-13", ["future"])

    rebuild_dates(["2026-09-13"])

    assert stored_ids("2026-09-13") == []


def test_rebuild_is_idempotent() -> None:
    midnight = stored_news("midnight", datetime(2026, 9, 11, 16, 0, tzinfo=UTC))
    store_articles([midnight])
    save_digest("2026-09-12", ["midnight"])

    rebuild_dates(["2026-09-12"])
    second = rebuild_dates(["2026-09-12"])[0]

    assert second.removed == []
    assert second.added == []
    assert stored_ids("2026-09-12") == ["midnight"]


def test_main_reports_the_diff(capsys) -> None:
    midnight = stored_news("midnight", datetime(2026, 9, 11, 16, 0, tzinfo=UTC))
    future = stored_news("future", datetime(2026, 9, 14, 0, 0, tzinfo=UTC))
    store_articles([midnight, future])
    save_digest("2026-09-12", ["future", "midnight"])

    assert main(["--dates", "2026-09-12"]) == 0

    output = capsys.readouterr().out
    assert "2026-09-12: 2 -> 1" in output
    assert "removed: future" in output
    assert "kept: midnight" in output
