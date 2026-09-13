"""Phase 7 persistence tests: SQLite storage, digests, and favorites."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db.repositories import (
    DigestRepository,
    FavoriteRepository,
    GitHubRepository,
    NewsRepository,
)
from app.db.session import new_session
from app.models import GitHubProject, NewsCategory, NewsItem
from app.services.digest_store import DigestStore, store
from app.services.digest_window import DigestWindow
from tests.conftest import FROZEN_NOW, day_feeds, make_fixture_fetch

UTC = timezone.utc

# 2026-09-10 10:00 in Asia/Shanghai: the local day these tests write digests
# for, so an article's calendar day matches the digest it is linked to.
PERSISTED_AT = datetime(2026, 9, 10, 2, 0, tzinfo=UTC)

# The issue window those persisted digests claim to cover, in UTC.
WINDOW_START = datetime(2026, 9, 9, 16, 0, tzinfo=UTC)
WINDOW_END = datetime(2026, 9, 10, 16, 0, tzinfo=UTC)


def window() -> DigestWindow:
    return DigestWindow(start=WINDOW_START, end=WINDOW_END)

def news_item(index: int, *, source: str = "OpenAI") -> NewsItem:
    return NewsItem(
        id=f"rss-{index:04d}",
        title_cn=f"标题 {index}",
        title_original=f"Title {index}",
        summary=f"摘要 {index}",
        why_it_matters="值得关注",
        source=source,
        source_type="official",
        published_at=PERSISTED_AT.isoformat(),
        category=NewsCategory.highlight,
        tags=[source],
        url=f"https://example.com/news/{index}",
        importance_score=index,
    )


def github_project(index: int) -> GitHubProject:
    return GitHubProject(
        id=f"gh-{index:04d}",
        repo=f"acme/repo-{index}",
        name=f"repo-{index}",
        description="desc",
        language="Python",
        stars=100 * index,
        stars_delta=index,
        summary_cn="中文摘要",
        why_it_matters="",
        url=f"https://github.com/acme/repo-{index}",
        rank=index,
        forks=5,
        license="MIT",
        topics=["llm"],
    )


# --- schema and upsert behaviour ---


def test_database_init_creates_tables() -> None:
    session = new_session()
    try:
        assert DigestRepository(session).count() == 0
        assert NewsRepository(session).count() == 0
        assert GitHubRepository(session).count() == 0
        assert FavoriteRepository(session).count() == 0
    finally:
        session.close()


def test_news_upsert_does_not_duplicate() -> None:
    session = new_session()
    try:
        repository = NewsRepository(session)
        repository.upsert_many([news_item(1)])
        repository.upsert_many([news_item(1)])
        session.commit()
        assert repository.count() == 1
        stored = repository.get("rss-0001")
        assert stored is not None
        assert stored.title_cn == "标题 1"
    finally:
        session.close()


def test_news_upsert_updates_existing_row() -> None:
    session = new_session()
    try:
        repository = NewsRepository(session)
        repository.upsert_many([news_item(1)])
        session.commit()
        updated = news_item(1).model_copy(update={"title_cn": "新标题"})
        repository.upsert_many([updated])
        session.commit()
        assert repository.count() == 1
        assert repository.get("rss-0001").title_cn == "新标题"
    finally:
        session.close()


def test_github_upsert_does_not_duplicate() -> None:
    session = new_session()
    try:
        repository = GitHubRepository(session)
        repository.upsert_many([github_project(1)])
        repository.upsert_many([github_project(1)])
        session.commit()
        assert repository.count() == 1
        stored = repository.get("gh-0001")
        assert stored is not None
        assert stored.repo == "acme/repo-1"
        assert stored.topics == ["llm"]
    finally:
        session.close()


# --- digest behaviour ---


def test_digest_create_and_read() -> None:
    session = new_session()
    try:
        NewsRepository(session).upsert_many([news_item(1), news_item(2)])
        GitHubRepository(session).upsert_many([github_project(1)])
        DigestRepository(session).save(
            date="2026-09-10",
            title="今日 AI 日报",
            description="desc",
            news_ids=["rss-0001", "rss-0002"],
            github_ids=["gh-0001"],
        )
        session.commit()
        repository = DigestRepository(session)
        assert repository.exists("2026-09-10")
        assert [item.id for item in repository.get_news("2026-09-10")] == ["rss-0001", "rss-0002"]
        assert [item.id for item in repository.get_github("2026-09-10")] == ["gh-0001"]
    finally:
        session.close()


def test_same_day_save_updates_single_digest() -> None:
    session = new_session()
    try:
        NewsRepository(session).upsert_many([news_item(1), news_item(2)])
        repository = DigestRepository(session)
        repository.save(
            date="2026-09-10",
            title="v1",
            description="first",
            news_ids=["rss-0001"],
            github_ids=[],
            window_start=WINDOW_START,
            window_end=WINDOW_END,
        )
        session.commit()
        repository.save(
            date="2026-09-10",
            title="v2",
            description="second",
            news_ids=["rss-0002", "rss-0001"],
            github_ids=[],
            window_start=WINDOW_START,
            window_end=WINDOW_END,
        )
        session.commit()
        assert repository.count() == 1
        # The ordering is replaced, not appended.
        assert [item.id for item in repository.get_news("2026-09-10")] == ["rss-0002", "rss-0001"]
        assert repository.get_meta("2026-09-10")[0:2] == ("v2", "second")
        assert repository.get_window("2026-09-10") == (WINDOW_START, WINDOW_END)
    finally:
        session.close()


def test_different_dates_create_separate_digests() -> None:
    session = new_session()
    try:
        NewsRepository(session).upsert_many([news_item(1), news_item(2)])
        repository = DigestRepository(session)
        repository.save(date="2026-09-10", title="d1", description="a", news_ids=["rss-0001"], github_ids=[])
        repository.save(date="2026-09-11", title="d2", description="b", news_ids=["rss-0002"], github_ids=[])
        session.commit()
        assert repository.count() == 2
        # History is not overwritten by a later day.
        assert [item.id for item in repository.get_news("2026-09-10")] == ["rss-0001"]
        assert [item.id for item in repository.get_news("2026-09-11")] == ["rss-0002"]
    finally:
        session.close()


def test_history_list_is_date_desc() -> None:
    session = new_session()
    try:
        NewsRepository(session).upsert_many([news_item(1), news_item(2), news_item(3)])
        repository = DigestRepository(session)
        repository.save(date="2026-09-10", title="d1", description="a", news_ids=["rss-0001"], github_ids=[])
        repository.save(date="2026-09-12", title="d3", description="c", news_ids=["rss-0003"], github_ids=[])
        repository.save(date="2026-09-11", title="d2", description="b", news_ids=["rss-0001", "rss-0002"], github_ids=[])
        session.commit()
        summaries = repository.list_summaries()
        assert [item[0] for item in summaries] == ["2026-09-12", "2026-09-11", "2026-09-10"]
        assert summaries[1][2] == 2
    finally:
        session.close()


def test_news_detail_from_history() -> None:
    session = new_session()
    try:
        NewsRepository(session).upsert_many([news_item(1)])
        DigestRepository(session).save(date="2026-09-01", title="old", description="a", news_ids=["rss-0001"], github_ids=[])
        session.commit()
        # A historical article stays readable after later digests are written.
        repository = NewsRepository(session)
        assert repository.get("rss-0001") is not None
    finally:
        session.close()


# --- favorites ---


def test_favorite_news_and_github() -> None:
    session = new_session()
    try:
        NewsRepository(session).upsert_many([news_item(1)])
        GitHubRepository(session).upsert_many([github_project(1)])
        repository = FavoriteRepository(session)
        news_row, created = repository.add("news", "rss-0001")
        project_row, _ = repository.add("github", "gh-0001")
        session.commit()
        assert created is True
        assert repository.count() == 2
        assert repository.exists("news", "rss-0001")
        assert repository.exists("github", "gh-0001")
        assert news_row.item_type == "news"
        assert project_row.item_type == "github"
    finally:
        session.close()


def test_duplicate_favorite_is_not_created_twice() -> None:
    session = new_session()
    try:
        repository = FavoriteRepository(session)
        first, created_first = repository.add("news", "rss-0001")
        second, created_second = repository.add("news", "rss-0001")
        session.commit()
        assert created_first is True
        assert created_second is False
        assert first.id == second.id
        assert repository.count() == 1
    finally:
        session.close()


def test_delete_favorite() -> None:
    session = new_session()
    try:
        repository = FavoriteRepository(session)
        row, _ = repository.add("news", "rss-0001")
        session.commit()
        assert repository.delete(row.id) is True
        session.commit()
        assert repository.count() == 0
        assert repository.delete(row.id) is False
    finally:
        session.close()


# --- transactions and durability ---


def test_rollback_discards_uncommitted_rows() -> None:
    session = new_session()
    try:
        NewsRepository(session).upsert_many([news_item(1)])
        session.flush()
        session.rollback()
    finally:
        session.close()

    session = new_session()
    try:
        assert NewsRepository(session).count() == 0
    finally:
        session.close()


def test_persist_failure_rolls_back_whole_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr("app.db.repositories.DigestRepository.save", boom)
    with pytest.raises(RuntimeError):
        store.persist(
            date="2026-09-10",
            window=window(),
            news_items=[news_item(1)],
            github_projects=[github_project(1)],
        )

    session = new_session()
    try:
        # Nothing from the failed write survived.
        assert NewsRepository(session).count() == 0
        assert DigestRepository(session).count() == 0
    finally:
        session.close()


def test_data_persists_across_sessions() -> None:
    store.persist(
        date="2026-09-10",
        window=window(),
        news_items=[news_item(1)],
        github_projects=[github_project(1)],
    )

    # A brand new store with no in-memory state still sees the rows.
    fresh = DigestStore()
    digest = fresh.get_digest("2026-09-10")
    assert digest.date == "2026-09-10"
    assert [item.id for item in digest.news] == ["rss-0001"]
    assert [item.id for item in digest.github_projects] == ["gh-0001"]


def test_failed_refresh_keeps_existing_digest() -> None:
    store.persist(
        date="2026-09-10",
        window=window(),
        news_items=[news_item(1)],
        github_projects=[github_project(1)],
    )
    saved = store.persist(date="2026-09-10", window=window(), news_items=[], github_projects=[])

    assert saved is False
    assert store.last_kept_previous is True
    digest = store.get_digest("2026-09-10")
    assert [item.id for item in digest.news] == ["rss-0001"]


def test_empty_github_result_keeps_linked_projects() -> None:
    """A GitHub outage on a later refresh must not erase the day's projects."""
    store.persist(
        date="2026-09-10",
        window=window(),
        news_items=[news_item(1)],
        github_projects=[github_project(1)],
    )
    store.persist(
        date="2026-09-10",
        window=window(),
        news_items=[news_item(2)],
        github_projects=None,
    )

    digest = store.get_digest("2026-09-10")
    assert [item.id for item in digest.github_projects] == ["gh-0001"]
    assert store.last_github_count == 1
    # The second refresh extends the digest instead of replacing it. The order
    # is the Phase 10.6 ranking, so this asserts content is preserved rather
    # than the append sequence: both articles are linked, ranked 1..N.
    assert {item.id for item in digest.news} == {"rss-0001", "rss-0002"}
    assert [item.rank for item in digest.news] == [1, 2]
    # rss-0002 carries the higher importance_score, so it leads the digest.
    assert digest.news[0].id == "rss-0002"


def test_refresh_second_day_creates_new_digest() -> None:
    """Each day publishes its own articles, so both digests get real news."""
    day_one = FROZEN_NOW
    day_two = day_one + timedelta(days=1)
    day_one_fetch = make_fixture_fetch(*day_feeds("2026-09-11"))
    day_two_fetch = make_fixture_fetch(*day_feeds("2026-09-12"))

    assert DigestStore().refresh(now=day_one, fetch_text=day_one_fetch)
    assert DigestStore().refresh(now=day_two, fetch_text=day_two_fetch)

    summaries = [row[0] for row in store.list_digest_summaries()]
    assert summaries == ["2026-09-12", "2026-09-11"]
    assert store.get_digest("2026-09-11").news
    assert store.get_digest("2026-09-12").news


def test_adjacent_digests_share_no_news() -> None:
    """A news_id belongs to exactly one calendar day, never to two digests."""
    day_one = FROZEN_NOW
    day_two = day_one + timedelta(days=1)
    day_one_fetch = make_fixture_fetch(*day_feeds("2026-09-11"))
    day_two_fetch = make_fixture_fetch(*day_feeds("2026-09-12"))

    DigestStore().refresh(now=day_one, fetch_text=day_one_fetch)
    DigestStore().refresh(now=day_two, fetch_text=day_two_fetch)

    first = {item.id for item in store.get_digest("2026-09-11").news}
    second = {item.id for item in store.get_digest("2026-09-12").news}
    assert first
    assert second
    assert first & second == set()


def test_same_day_refresh_updates_not_duplicates(
    openai_rss_xml: str,
    deepmind_rss_xml: str,
    huggingface_rss_xml: str,
) -> None:
    fetch = make_fixture_fetch(openai_rss_xml, deepmind_rss_xml, huggingface_rss_xml)
    moment = FROZEN_NOW
    store.refresh(now=moment, fetch_text=fetch)
    store.refresh(now=moment + timedelta(hours=1), fetch_text=fetch)

    assert len(store.list_digest_summaries()) == 1
    assert store.stats()[1] == 6


def test_stats_reports_totals() -> None:
    store.persist(
        date="2026-09-10",
        window=window(),
        news_items=[news_item(1), news_item(2)],
        github_projects=[github_project(1)],
    )
    digests, news_total, github_total = store.stats()
    assert (digests, news_total, github_total) == (1, 2, 1)
