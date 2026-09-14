"""Phase 10.10: no behavioural regression in the routes this phase touches.

The environment work changed how the process picks a database and when the
search index is created. That is exactly the kind of change that can quietly
break a read path, so the existing behaviour is asserted here rather than assumed
from the rest of the suite passing.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from tests.conftest import FROZEN_NOW, day_feeds, make_fixture_fetch


@pytest.fixture
def two_days(client) -> None:
    """Two consecutive real digests, so history and navigation have something."""
    from app.services.digest_store import DigestStore

    day_one = FROZEN_NOW
    day_two = day_one + timedelta(days=1)
    DigestStore().refresh(now=day_one, fetch_text=make_fixture_fetch(*day_feeds("2026-09-11")))
    DigestStore().refresh(now=day_two, fetch_text=make_fixture_fetch(*day_feeds("2026-09-12")))


def test_search_still_returns_ranked_hits(client) -> None:
    from app.services.digest_store import DigestStore

    DigestStore().refresh(now=FROZEN_NOW, fetch_text=make_fixture_fetch(*day_feeds("2026-09-11")))

    response = client.get("/api/v1/search", params={"q": "OpenAI story"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 1
    assert payload["items"][0]["news_id"]


def test_search_still_uses_the_documented_response_shape(client) -> None:
    """The search contract is unchanged: query / total / items, and no body."""
    response = client.get("/api/v1/search", params={"q": "anything"})

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"query", "total", "items"}
    assert payload["total"] == 0
    assert payload["items"] == []


def test_history_still_lists_real_digests_only(client, two_days) -> None:
    response = client.get("/api/v1/digests")

    assert response.status_code == 200
    dates = [item["date"] for item in response.json()]
    assert dates == ["2026-09-12", "2026-09-11"]
    assert all(item["news_count"] >= 0 for item in response.json())


def test_a_single_digest_still_returns_its_window(client, two_days) -> None:
    response = client.get("/api/v1/daily/2026-09-11")

    assert response.status_code == 200
    payload = response.json()
    assert payload["date"] == "2026-09-11"
    assert payload["window_start"] and payload["window_end"]


def test_ranking_fields_are_still_served(client) -> None:
    from app.services.digest_store import DigestStore

    DigestStore().refresh(now=FROZEN_NOW, fetch_text=make_fixture_fetch(*day_feeds("2026-09-11")))

    payload = client.get("/api/v1/daily/2026-09-11").json()
    news = payload["news"]

    assert news
    # rank is assigned in reading order, and the top story flags survive.
    assert [item["rank"] for item in news] == list(range(1, len(news) + 1))
    assert all("is_top_story" in item for item in news)
    assert all("rank_score" in item for item in news)


def test_detail_still_returns_the_original_body(client) -> None:
    from app.services.digest_store import DigestStore

    DigestStore().refresh(now=FROZEN_NOW, fetch_text=make_fixture_fetch(*day_feeds("2026-09-11")))
    news_id = client.get("/api/v1/daily/2026-09-11").json()["news"][0]["id"]

    response = client.get(f"/api/v1/news/{news_id}")

    assert response.status_code == 200
    assert "content_original" in response.json()


def test_the_list_view_still_hides_the_body(client) -> None:
    from app.services.digest_store import DigestStore

    DigestStore().refresh(now=FROZEN_NOW, fetch_text=make_fixture_fetch(*day_feeds("2026-09-11")))

    payload = client.get("/api/v1/daily/2026-09-11").json()

    assert "content_original" not in payload["news"][0]


def test_system_status_still_reports_ok(client) -> None:
    payload = client.get("/api/v1/system/status").json()

    assert payload["status"] == "ok"
    assert payload["database"] == "ok"


def test_health_still_works(client) -> None:
    assert client.get("/health").json() == {"status": "ok"}
