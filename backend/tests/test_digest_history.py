"""Phase 10.8: digest history is a list of real digests, not a calendar.

These tests cover what the history screen and its date navigation depend on:
/digests describes stored days without shipping their content, a day that was
never generated has no digest (and 404s), and every read comes from SQLite
rather than re-running collection.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.repositories import DigestRepository, NewsRepository
from app.db.session import new_session
from app.models import NewsCategory, NewsItem
from app.services.digest_store import DigestStore
from tests.conftest import FROZEN_NOW, day_feeds, make_fixture_fetch

UTC = timezone.utc


def stored_news(news_id: str, published_at: datetime) -> NewsItem:
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


def seed_two_days() -> None:
    """09-11 and 09-13 exist. 09-12 was never generated (a missed refresh)."""
    session = new_session()
    try:
        repository = DigestRepository(session)
        for news_id, date, minute in (
            ("rss-a", "2026-09-11", 0),
            ("rss-b", "2026-09-11", 30),
            ("rss-c", "2026-09-13", 10),
        ):
            base = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=UTC)
            NewsRepository(session).upsert_many(
                [stored_news(news_id, base + timedelta(hours=11, minutes=minute))]
            )
        repository.save(
            date="2026-09-11",
            title="今日 AI 日报",
            description="",
            news_ids=["rss-a", "rss-b"],
            github_ids=[],
            window_start=datetime(2026, 9, 10, 0, 0, tzinfo=UTC),
            window_end=datetime(2026, 9, 11, 0, 0, tzinfo=UTC),
        )
        repository.save(
            date="2026-09-13",
            title="今日 AI 日报",
            description="",
            news_ids=["rss-c"],
            github_ids=[],
            window_start=datetime(2026, 9, 12, 0, 0, tzinfo=UTC),
            window_end=datetime(2026, 9, 13, 0, 0, tzinfo=UTC),
        )
        session.commit()
    finally:
        session.close()


# --- /digests ---


def test_digests_are_date_desc(client) -> None:
    day_one = FROZEN_NOW
    day_two = day_one + timedelta(days=1)
    DigestStore().refresh(now=day_one, fetch_text=make_fixture_fetch(*day_feeds("2026-09-11")))
    DigestStore().refresh(now=day_two, fetch_text=make_fixture_fetch(*day_feeds("2026-09-12")))

    dates = [row["date"] for row in client.get("/api/v1/digests").json()]

    assert dates == ["2026-09-12", "2026-09-11"]


def test_digests_lists_only_days_that_exist(client) -> None:
    seed_two_days()

    dates = [row["date"] for row in client.get("/api/v1/digests").json()]

    assert dates == ["2026-09-13", "2026-09-11"]
    assert "2026-09-12" not in dates


def test_digests_reports_the_window_and_top_story_count(client) -> None:
    seed_two_days()

    by_date = {row["date"]: row for row in client.get("/api/v1/digests").json()}
    day = by_date["2026-09-11"]

    assert day["news_count"] == 2
    assert day["top_story_count"] == 2
    assert day["window_start"] == "2026-09-10T00:00:00+00:00"
    assert day["window_end"] == "2026-09-11T00:00:00+00:00"


def test_digests_is_empty_when_nothing_was_ever_generated() -> None:
    """An untouched database reports no history rather than a fabricated day."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        assert test_client.get("/api/v1/digests").json() == []


# --- one day's digest ---


def test_daily_by_date_returns_that_days_stories(client) -> None:
    seed_two_days()

    payload = client.get("/api/v1/daily/2026-09-11").json()

    assert [item["id"] for item in payload["news"]] == ["rss-a", "rss-b"]
    assert payload["window_start"] == "2026-09-10T00:00:00+00:00"
    assert payload["window_end"] == "2026-09-11T00:00:00+00:00"


def test_daily_by_date_carries_the_rank(client) -> None:
    seed_two_days()

    ranks = [item["rank"] for item in client.get("/api/v1/daily/2026-09-11").json()["news"]]

    assert ranks == [1, 2]


def test_adjacent_days_share_no_news(client) -> None:
    seed_two_days()

    first = {item["id"] for item in client.get("/api/v1/daily/2026-09-11").json()["news"]}
    second = {item["id"] for item in client.get("/api/v1/daily/2026-09-13").json()["news"]}

    assert first
    assert second
    assert first & second == set()


def test_a_day_without_a_digest_is_404(client) -> None:
    """The gap must read as "no digest", never as an empty or invented one."""
    seed_two_days()

    response = client.get("/api/v1/daily/2026-09-12")

    assert response.status_code == 404


def test_github_projects_come_from_the_requested_day(client) -> None:
    """A historical digest shows the projects stored for it, not today's."""
    day_one = FROZEN_NOW
    day_two = day_one + timedelta(days=1)
    DigestStore().refresh(now=day_one, fetch_text=make_fixture_fetch(*day_feeds("2026-09-11")))
    DigestStore().refresh(now=day_two, fetch_text=make_fixture_fetch(*day_feeds("2026-09-12")))

    for date in ("2026-09-11", "2026-09-12"):
        payload = client.get(f"/api/v1/daily/{date}").json()
        ids = {project["id"] for project in payload["github_projects"]}
        listed = {row["id"] for row in client.get(f"/api/v1/github?date={date}").json()}
        assert ids == listed


# --- reading history does not collect ---


def test_reading_history_never_runs_collection(client, monkeypatch) -> None:
    """Opening a past digest must not fetch RSS, GitHub, or call the LLM."""
    seed_two_days()

    def fail(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("history reads must not collect")

    monkeypatch.setattr("app.collectors.rss.fetch_rss_text", fail)
    monkeypatch.setattr("app.collectors.html.fetch_html", fail)
    monkeypatch.setattr("app.collectors.github_trending.fetch_trending_html", fail)

    assert client.get("/api/v1/digests").status_code == 200
    assert client.get("/api/v1/daily/2026-09-11").status_code == 200
    assert client.get("/api/v1/github?date=2026-09-11").status_code == 200


# --- the digest keeps its content ---


def test_history_snapshot_survives_a_later_refresh(client) -> None:
    """A digest is a snapshot: a later day must not rewrite it."""
    day_one = FROZEN_NOW
    day_two = day_one + timedelta(days=1)
    DigestStore().refresh(now=day_one, fetch_text=make_fixture_fetch(*day_feeds("2026-09-11")))
    before = client.get("/api/v1/daily/2026-09-11").json()

    DigestStore().refresh(now=day_two, fetch_text=make_fixture_fetch(*day_feeds("2026-09-12")))

    after = client.get("/api/v1/daily/2026-09-11").json()
    assert after["news"] == before["news"]
    assert after["github_projects"] == before["github_projects"]
    assert after["window_end"] == before["window_end"]


def test_news_detail_from_a_historical_digest_still_works(client) -> None:
    seed_two_days()
    digest = client.get("/api/v1/daily/2026-09-11").json()

    detail = client.get(f"/api/v1/news/{digest['news'][0]['id']}")

    assert detail.status_code == 200
    assert detail.json()["id"] == digest["news"][0]["id"]


def test_favoriting_from_a_historical_digest_uses_the_same_news_id(client) -> None:
    seed_two_days()
    digest = client.get("/api/v1/daily/2026-09-11").json()
    news_id = digest["news"][0]["id"]

    created = client.post("/api/v1/favorites", json={"item_type": "news", "item_id": news_id})

    assert created.status_code == 201
    assert created.json()["item"]["id"] == news_id
    # Still one favorite row, keyed by the original news id.
    assert len(client.get("/api/v1/favorites").json()) == 1


# --- issue window does not regress ---


def test_a_future_article_reaches_no_digest(client) -> None:
    """The Phase 10.2 window rule still excludes future timestamps."""
    seed_two_days()
    session = new_session()
    try:
        # Published after every stored digest's window_end.
        NewsRepository(session).upsert_many(
            [stored_news("rss-future", datetime(2026, 9, 14, 0, 0, tzinfo=UTC))]
        )
        session.commit()
    finally:
        session.close()

    for date in ("2026-09-11", "2026-09-13"):
        ids = {item["id"] for item in client.get(f"/api/v1/daily/{date}").json()["news"]}
        assert "rss-future" not in ids
