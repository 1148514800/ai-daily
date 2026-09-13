"""Phase 10.6 integration: ranking reaches storage, the API, and old databases.

The unit tests in ``test_news_ranker`` cover the score itself. These cover the
seams: that a refresh stores the order it ranked, that the API reports every
article with its rank and top-story flag, that a second refresh on the same day
is stable, and that a database written before ranking existed still opens.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db.repositories import NewsRepository
from app.db.session import configure_database, init_db, new_session
from app.models import NewsCategory, NewsItem
from app.services.digest_store import DigestStore, store
from app.services.digest_window import DigestWindow
from tests.conftest import FROZEN_NOW, day_feeds, make_fixture_fetch

UTC = timezone.utc

PERSISTED_AT = datetime(2026, 9, 10, 2, 0, tzinfo=UTC)
WINDOW_START = datetime(2026, 9, 9, 16, 0, tzinfo=UTC)
WINDOW_END = datetime(2026, 9, 10, 16, 0, tzinfo=UTC)


def window() -> DigestWindow:
    return DigestWindow(start=WINDOW_START, end=WINDOW_END)


def news_item(
    index: int,
    *,
    importance: int | None = None,
    source: str = "OpenAI",
    source_type: str = "official",
    title: str | None = None,
) -> NewsItem:
    return NewsItem(
        id=f"rss-{index:04d}",
        title_cn=title or f"标题 {index}",
        title_original=title or f"Title {index}",
        summary=f"摘要 {index}",
        why_it_matters="值得关注",
        source=source,
        source_type=source_type,
        published_at=PERSISTED_AT.isoformat(),
        category=NewsCategory.highlight,
        tags=[source],
        url=f"https://example.com/news/{index}",
        importance_score=importance if importance is not None else index,
    )


# --- persistence ---


def test_persist_stores_rank_and_score_on_the_digest_link() -> None:
    """Rank belongs to the digest-to-news link, not to the article."""
    store.persist(
        date="2026-09-10",
        window=window(),
        news_items=[news_item(1, importance=20), news_item(2, importance=95)],
        github_projects=None,
    )

    digest = store.get_digest("2026-09-10")
    # The stronger story leads, regardless of the order it was passed in.
    assert [item.id for item in digest.news] == ["rss-0002", "rss-0001"]
    assert [item.rank for item in digest.news] == [1, 2]
    assert digest.news[0].rank_score is not None
    assert digest.news[0].rank_score > digest.news[1].rank_score

    # The article itself carries no rank when read on its own.
    session = new_session()
    try:
        assert NewsRepository(session).get("rss-0002").rank is None
    finally:
        session.close()


def test_persist_keeps_every_article_not_just_the_top_stories() -> None:
    items = [news_item(index, importance=100 - index) for index in range(1, 16)]
    store.persist(
        date="2026-09-10", window=window(), news_items=items, github_projects=None
    )

    digest = store.get_digest("2026-09-10")
    assert len(digest.news) == 15
    assert sum(1 for item in digest.news if item.is_top_story) == 10
    assert sum(1 for item in digest.news if not item.is_top_story) == 5


def test_top_story_flag_follows_the_configured_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """The flag is derived on read, so the limit can change without a rewrite."""
    store.persist(
        date="2026-09-10",
        window=window(),
        news_items=[news_item(index, importance=100 - index) for index in range(1, 6)],
        github_projects=None,
    )

    monkeypatch.setenv("TOP_STORY_LIMIT", "2")
    digest = store.get_digest("2026-09-10")

    assert [item.is_top_story for item in digest.news] == [True, True, False, False, False]


def test_second_refresh_on_the_same_day_is_rank_stable() -> None:
    """Re-running the same refresh must not reshuffle the digest."""
    items = [news_item(index, importance=50 + index) for index in range(1, 7)]
    store.persist(
        date="2026-09-10", window=window(), news_items=items, github_projects=None
    )
    first = [(item.id, item.rank, item.rank_score) for item in store.get_digest("2026-09-10").news]

    # A second refresh collects the same articles again.
    store.persist(
        date="2026-09-10", window=window(), news_items=items, github_projects=None
    )
    second = [
        (item.id, item.rank, item.rank_score) for item in store.get_digest("2026-09-10").news
    ]

    assert first == second


def test_second_refresh_extends_the_digest_and_re_ranks_the_whole_list() -> None:
    """A later refresh merges its articles and ranks the union, not the delta."""
    store.persist(
        date="2026-09-10",
        window=window(),
        news_items=[news_item(1, importance=10)],
        github_projects=None,
    )
    store.persist(
        date="2026-09-10",
        window=window(),
        news_items=[news_item(2, importance=90)],
        github_projects=None,
    )

    digest = store.get_digest("2026-09-10")
    assert [item.id for item in digest.news] == ["rss-0002", "rss-0001"]
    assert {item.id for item in digest.news} == {"rss-0001", "rss-0002"}


def test_ranking_does_not_regress_the_issue_window() -> None:
    """Ranking runs after the window filter, so it cannot admit an outsider."""
    outside = news_item(99).model_copy(
        update={"published_at": (PERSISTED_AT + timedelta(days=30)).isoformat()}
    )
    store.persist(
        date="2026-09-10",
        window=window(),
        news_items=[news_item(1), outside],
        github_projects=None,
    )

    digest = store.get_digest("2026-09-10")
    assert [item.id for item in digest.news] == ["rss-0001"]
    # The out-of-window article is still stored, just not linked.
    session = new_session()
    try:
        assert NewsRepository(session).get("rss-0099") is not None
    finally:
        session.close()


def test_ranking_stats_are_recorded_for_observability() -> None:
    store.persist(
        date="2026-09-10",
        window=window(),
        news_items=[
            news_item(1, title="OpenAI launches GPT-8", importance=90),
            news_item(2, title="NVIDIA announces a GPU", source="NVIDIA", importance=70),
        ],
        github_projects=None,
    )

    stats = store.last_ranking_stats
    assert stats.candidates == 2
    assert stats.top_stories == 2
    assert stats.companies == 2
    assert stats.topics >= 2


def test_ranking_survives_a_short_digest() -> None:
    store.persist(
        date="2026-09-10",
        window=window(),
        news_items=[news_item(1)],
        github_projects=None,
    )

    digest = store.get_digest("2026-09-10")
    assert len(digest.news) == 1
    assert digest.news[0].rank == 1
    assert digest.news[0].is_top_story is True


# --- API ---


@pytest.fixture
def ranked_client(patch_rss_feeds):
    """A client backed by one refresh over the fixture feeds."""
    from app.main import app
    from app.services.refresh_service import refresh_all

    refresh_all(now=FROZEN_NOW)
    with TestClient(app) as test_client:
        yield test_client


def test_daily_api_returns_rank_fields_in_rank_order(ranked_client: TestClient) -> None:
    response = ranked_client.get("/api/v1/daily")
    assert response.status_code == 200
    news = response.json()["news"]

    assert news
    assert [item["rank"] for item in news] == list(range(1, len(news) + 1))
    # Every story carries the flag, and the leading ones are marked.
    assert all(isinstance(item["is_top_story"], bool) for item in news)
    assert news[0]["is_top_story"] is True
    scores = [item["rank_score"] for item in news]
    assert scores == sorted(scores, reverse=True)


def test_daily_api_keeps_every_existing_field(ranked_client: TestClient) -> None:
    """Ranking is additive: no field an older client reads may disappear."""
    body = ranked_client.get("/api/v1/daily").json()
    first = body["news"][0]

    for field in (
        "id",
        "title_cn",
        "title_original",
        "summary",
        "why_it_matters",
        "source",
        "source_type",
        "published_at",
        "category",
        "tags",
        "url",
        "importance_score",
    ):
        assert field in first, field


def test_daily_api_does_not_leak_the_article_body(ranked_client: TestClient) -> None:
    """The digest list stays lean; only the detail endpoint ships the body."""
    first = ranked_client.get("/api/v1/daily").json()["news"][0]

    assert "content_original" not in first


def test_daily_api_by_date_is_ranked_too(ranked_client: TestClient) -> None:
    today = ranked_client.get("/api/v1/daily").json()["date"]
    news = ranked_client.get(f"/api/v1/daily/{today}").json()["news"]

    assert news
    assert [item["rank"] for item in news] == list(range(1, len(news) + 1))


def test_news_detail_still_returns_the_original_body(ranked_client: TestClient) -> None:
    """Article detail must not regress: ranking is a list-level concern."""
    first = ranked_client.get("/api/v1/daily").json()["news"][0]
    detail = ranked_client.get(f"/api/v1/news/{first['id']}")

    assert detail.status_code == 200
    body = detail.json()
    assert "content_original" in body
    assert body["content_language"] is not None


# --- schema upgrade ---


def _create_pre_ranking_database(path: Path) -> None:
    """Write a database whose daily_digest_news has no rank columns.

    This is the shape a Phase 10.5 install has on disk, and opening it must work
    without a migration framework.
    """
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE news_articles (
                id VARCHAR(64) PRIMARY KEY,
                title_cn TEXT DEFAULT '',
                title_original TEXT DEFAULT '',
                summary TEXT DEFAULT '',
                why_it_matters TEXT DEFAULT '',
                source VARCHAR(128) DEFAULT '',
                source_type VARCHAR(64) DEFAULT '',
                published_at DATETIME,
                category VARCHAR(32) DEFAULT 'highlight',
                url TEXT DEFAULT '',
                canonical_url TEXT DEFAULT '',
                importance_score INTEGER,
                content_original TEXT DEFAULT '',
                content_language VARCHAR(16) DEFAULT '',
                content_extraction_method VARCHAR(32) DEFAULT '',
                content_fetched_at DATETIME,
                created_at DATETIME,
                updated_at DATETIME
            );
            CREATE TABLE daily_digests (
                date VARCHAR(10) PRIMARY KEY,
                title TEXT DEFAULT '',
                description TEXT DEFAULT '',
                window_start DATETIME,
                window_end DATETIME,
                notified_at DATETIME,
                created_at DATETIME,
                updated_at DATETIME
            );
            CREATE TABLE daily_digest_news (
                digest_date VARCHAR(10) NOT NULL,
                news_id VARCHAR(64) NOT NULL,
                position INTEGER DEFAULT 0,
                PRIMARY KEY (digest_date, news_id)
            );
            """
        )
        connection.execute(
            "INSERT INTO news_articles (id, title_cn, title_original, source, source_type,"
            " published_at, url, canonical_url, importance_score)"
            " VALUES ('rss-old', '旧标题', 'Old title', 'OpenAI', 'official',"
            " '2026-09-10 02:00:00', 'https://example.com/old', 'https://example.com/old', 70)"
        )
        connection.execute(
            "INSERT INTO daily_digests (date, title, description, window_start, window_end)"
            " VALUES ('2026-09-10', '今日 AI 日报', 'd', '2026-09-09 16:00:00',"
            " '2026-09-10 16:00:00')"
        )
        connection.execute(
            "INSERT INTO daily_digest_news (digest_date, news_id, position)"
            " VALUES ('2026-09-10', 'rss-old', 0)"
        )
        connection.commit()
    finally:
        connection.close()


def test_old_database_is_upgraded_with_rank_columns(tmp_path: Path) -> None:
    """Opening a pre-ranking database adds the columns and still reads the day."""
    db_path = tmp_path / "old_ai_daily.db"
    _create_pre_ranking_database(db_path)
    configure_database(f"sqlite:///{db_path.as_posix()}")
    try:
        init_db()
        columns = {
            row[1]
            for row in _pragma_columns(db_path, "daily_digest_news")
        }
        assert {"rank", "rank_score"} <= columns

        digest = DigestStore().get_digest("2026-09-10")
        assert [item.id for item in digest.news] == ["rss-old"]
        # Rank is derived from the stored position, so a pre-ranking row reads
        # back as rank 1 with no score rather than as an error.
        assert digest.news[0].rank == 1
        assert digest.news[0].rank_score is None
    finally:
        configure_database("sqlite://")


def _pragma_columns(path: Path, table: str) -> list[tuple]:
    connection = sqlite3.connect(path)
    try:
        return list(connection.execute(f'PRAGMA table_info("{table}")'))
    finally:
        connection.close()


def test_old_digest_can_be_re_ranked_by_a_later_refresh(tmp_path: Path) -> None:
    """A refresh over an upgraded database writes real rank scores."""
    db_path = tmp_path / "old_ai_daily.db"
    _create_pre_ranking_database(db_path)
    configure_database(f"sqlite:///{db_path.as_posix()}")
    try:
        init_db()
        store.persist(
            date="2026-09-10",
            window=window(),
            news_items=[news_item(1, importance=40)],
            github_projects=None,
        )
        digest = store.get_digest("2026-09-10")
        assert len(digest.news) == 2
        assert all(item.rank_score is not None for item in digest.news)
        assert [item.rank for item in digest.news] == [1, 2]
    finally:
        configure_database("sqlite://")


# --- end to end ---


def test_full_refresh_ranks_the_fixture_digest() -> None:
    """One complete refresh produces a ranked, deduped, windowed digest."""
    fetch = make_fixture_fetch(*day_feeds("2026-09-11"))
    assert DigestStore().refresh(now=FROZEN_NOW, fetch_text=fetch)

    digest = store.get_digest("2026-09-11")
    assert digest.news
    assert [item.rank for item in digest.news] == list(range(1, len(digest.news) + 1))
    assert all(item.rank_score is not None for item in digest.news)
    # The digest is still one per day and the neighbors stay disjoint.
    assert len({item.id for item in digest.news}) == len(digest.news)
