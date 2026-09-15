"""Phase 10.11: the body is fetched only when it is asked for.

The detail screen used to receive the whole article with the metadata, which
made opening one story cost as much as a page of them. The two routes are
separated here: the detail response describes the stored body, and a second
request returns the text.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.repositories import NewsRepository
from app.db.session import new_session
from app.models import NewsCategory, NewsItem

BODY = (
    "Cohere released North Small Translate today, an open-weight machine "
    "translation model aimed at regulated industries.\n\n"
    "The company says the model is available under a permissive licence."
)


def store_article(news_id: str, **overrides) -> None:
    fields = dict(
        id=news_id,
        title_cn="中文标题",
        title_original="An original title",
        summary="中文摘要",
        why_it_matters="为什么值得关注",
        source="Cohere",
        source_type="official",
        published_at="2026-09-13T06:00:00+00:00",
        category=NewsCategory.highlight,
        tags=["Cohere"],
        url=f"https://cohere.com/blog/{news_id}",
    )
    fields.update(overrides)
    session = new_session()
    try:
        NewsRepository(session).upsert_many([NewsItem(**fields)])
        session.commit()
    finally:
        session.close()


def test_the_detail_response_describes_the_body_without_shipping_it(client: TestClient) -> None:
    store_article(
        "rss-bodies",
        content_original=BODY,
        content_language="en",
        content_extraction_method="web",
        content_quality="good",
    )

    payload = client.get("/api/v1/news/rss-bodies").json()

    assert "content_original" not in payload
    assert payload["has_content"] is True
    assert payload["content_language"] == "en"
    assert payload["content_extraction_method"] == "web"
    assert payload["content_quality"] == "good"


def test_the_detail_response_still_carries_every_list_field(client: TestClient) -> None:
    """The response is the list shape plus a description of the body."""
    store_article("rss-shape", content_original=BODY, content_language="en")

    payload = client.get("/api/v1/news/rss-shape").json()

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
        "topic",
        "company",
    ):
        assert field in payload, field


def test_the_content_endpoint_returns_the_clean_body(client: TestClient) -> None:
    store_article(
        "rss-content",
        content_original=BODY,
        content_language="en",
        content_extraction_method="web",
        content_quality="good",
    )

    payload = client.get("/api/v1/news/rss-content/content").json()

    assert payload["news_id"] == "rss-content"
    assert payload["content_original"] == BODY
    assert payload["content_language"] == "en"
    assert payload["content_extraction_method"] == "web"
    assert payload["content_quality"] == "good"


def test_the_content_response_is_only_the_body_fields(client: TestClient) -> None:
    """No metadata is repeated: the detail response already carried it."""
    store_article("rss-minimal", content_original=BODY, content_language="en")

    payload = client.get("/api/v1/news/rss-minimal/content").json()

    assert set(payload) == {
        "news_id",
        "content_original",
        "content_language",
        "content_extraction_method",
        "content_quality",
    }
    assert "title_cn" not in payload
    assert "summary" not in payload


def test_an_article_with_no_body_returns_an_empty_body_not_an_error(client: TestClient) -> None:
    """An article that exists without text is a normal state, not a 404."""
    store_article("rss-empty")

    detail = client.get("/api/v1/news/rss-empty")
    content = client.get("/api/v1/news/rss-empty/content")

    assert detail.status_code == 200
    assert detail.json()["has_content"] is False
    assert content.status_code == 200
    payload = content.json()
    assert payload["content_original"] == ""
    assert payload["content_language"] == ""
    assert payload["news_id"] == "rss-empty"


@pytest.mark.parametrize("news_id", ["nope", "rss-does-not-exist"])
def test_an_unknown_article_is_a_404_on_both_routes(client: TestClient, news_id: str) -> None:
    assert client.get(f"/api/v1/news/{news_id}").status_code == 404
    assert client.get(f"/api/v1/news/{news_id}/content").status_code == 404


def test_the_digest_list_never_carries_the_body(client: TestClient) -> None:
    for index in range(3):
        store_article(f"rss-list-{index}", content_original=BODY, content_language="en")

    news = client.get("/api/v1/daily").json()["news"]

    assert news
    for item in news:
        assert "content_original" not in item
        assert "has_content" not in item
        assert "content_quality" not in item


def test_the_body_is_absent_from_the_search_and_favourites_payloads(client: TestClient) -> None:
    """The on-demand rule holds everywhere the body used to leak."""
    store_article("rss-quiet", content_original=BODY, content_language="en", title_cn="Cohere 发布新模型")
    created = client.post("/api/v1/favorites", json={"item_type": "news", "item_id": "rss-quiet"})
    assert created.status_code in {200, 201}

    favourites = client.get("/api/v1/favorites").json()
    assert favourites
    assert all("content_original" not in item["item"] for item in favourites)

    hits = client.get("/api/v1/search", params={"q": "Cohere"}).json()["items"]
    assert all("content_original" not in hit for hit in hits)


def test_a_quality_verdict_is_reported_with_the_content(client: TestClient) -> None:
    store_article(
        "rss-low",
        content_original="A short feed teaser.",
        content_language="en",
        content_extraction_method="rss_summary",
        content_quality="low",
    )

    payload = client.get("/api/v1/news/rss-low/content").json()

    # The backend says what it has instead of presenting a teaser as the article.
    assert payload["content_quality"] == "low"
    assert payload["content_extraction_method"] == "rss_summary"
    assert payload["content_original"] == "A short feed teaser."
