"""Phase 10.12: the structured Chinese summary.

The enrichment grew a fourth field: ``key_points``, the 3-5 short bullets behind
核心信息 on the detail page. These tests cover the whole path the field travels —
the LLM schema, the stored JSON column, the API payload — and the compatibility
rule that makes the upgrade safe: an article summarised before the field existed
must still load and must report an empty list rather than an error.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.repositories import NewsRepository, _key_points, key_points_json
from app.db.session import configure_database, init_db, new_session, reset_database
from app.models import NewsCategory, NewsItem
from app.services.llm.enrich import clean_key_points
from app.services.llm.prompts import PROMPT_VERSION, SYSTEM_PROMPT
from app.services.llm.schemas import ArticleEnrichment

POINTS = ["发布方：Cohere", "模型：North Small Translate", "许可：开源权重"]


def article(news_id: str, **overrides) -> NewsItem:
    fields = dict(
        id=news_id,
        title_cn="中文标题",
        title_original="An original title",
        summary="中文摘要",
        why_it_matters="为什么重要",
        source="Cohere",
        source_type="official",
        published_at="2026-09-15T06:00:00+00:00",
        category=NewsCategory.highlight,
        tags=["Cohere"],
        url=f"https://cohere.com/blog/{news_id}",
    )
    fields.update(overrides)
    return NewsItem(**fields)


def store(item: NewsItem) -> None:
    session = new_session()
    try:
        NewsRepository(session).upsert_many([item])
        session.commit()
    finally:
        session.close()


# --- the schema -----------------------------------------------------------------


def test_an_enrichment_without_key_points_still_validates() -> None:
    """The v2 payload has no key_points; it must not become a validation error."""
    parsed = ArticleEnrichment.model_validate(
        {"title_cn": "标题", "summary_cn": "摘要", "why_it_matters": "", "importance_score": 50}
    )

    assert parsed.key_points == []


def test_key_points_are_read_from_a_v3_payload() -> None:
    parsed = ArticleEnrichment.model_validate(
        {
            "title_cn": "标题",
            "summary_cn": "摘要",
            "key_points": POINTS,
            "why_it_matters": "",
            "importance_score": 50,
        }
    )

    assert parsed.key_points == POINTS


def test_a_null_key_points_field_becomes_an_empty_list() -> None:
    """A model that answers with an explicit null must not fail the article."""
    parsed = ArticleEnrichment.model_validate(
        {
            "title_cn": "标题",
            "summary_cn": "摘要",
            "key_points": None,
            "why_it_matters": "",
            "importance_score": 50,
        }
    )

    assert parsed.key_points == []


# --- the bullet cleaner ---------------------------------------------------------


def test_clean_key_points_trims_and_drops_blanks() -> None:
    assert clean_key_points(["  发布方：Cohere ", "", "   ", "模型：North"]) == [
        "发布方：Cohere",
        "模型：North",
    ]


def test_clean_key_points_drops_repeats_and_keeps_order() -> None:
    assert clean_key_points(["A", "B", "A"]) == ["A", "B"]


def test_clean_key_points_leaves_a_short_list_alone() -> None:
    """Two real points are shorter, not invalid: the count is not padded to 3."""
    assert clean_key_points(["只有一条"]) == ["只有一条"]


def test_clean_key_points_tolerates_a_missing_list() -> None:
    assert clean_key_points(None) == []


# --- storage --------------------------------------------------------------------


def test_key_points_round_trip_through_the_database() -> None:
    store(article("rss-points", key_points=POINTS))

    session = new_session()
    try:
        stored = NewsRepository(session).get("rss-points")
    finally:
        session.close()

    assert stored is not None
    assert stored.key_points == POINTS


def test_an_article_with_no_points_stores_an_empty_list() -> None:
    store(article("rss-none"))

    session = new_session()
    try:
        stored = NewsRepository(session).get("rss-none")
    finally:
        session.close()

    assert stored is not None
    assert stored.key_points == []


def test_a_later_enrichment_replaces_the_points() -> None:
    """A re-summarised article must show the new bullets, not the old ones."""
    store(article("rss-replace", key_points=POINTS))
    store(article("rss-replace", key_points=["新的要点"]))

    session = new_session()
    try:
        stored = NewsRepository(session).get("rss-replace")
    finally:
        session.close()

    assert stored is not None
    assert stored.key_points == ["新的要点"]


def test_key_points_json_drops_blanks_and_duplicates() -> None:
    assert json.loads(key_points_json([" A ", "A", "", "B"])) == ["A", "B"]


def test_a_malformed_stored_value_reads_back_as_no_points() -> None:
    """A truncated or hand-edited column must not break every list it appears in."""

    class Row:
        key_points_json = "not json"

    assert _key_points(Row()) == []


def test_a_stored_object_instead_of_an_array_reads_back_as_no_points() -> None:
    class Row:
        key_points_json = '{"a": 1}'

    assert _key_points(Row()) == []


def test_a_missing_column_reads_back_as_no_points() -> None:
    """The pre-Phase-10.12 row shape simply has no attribute to read."""

    class Row:
        pass

    assert _key_points(Row()) == []


def test_stored_points_that_are_not_strings_are_dropped() -> None:
    """A hand-edited column must not render "None" as a bullet."""

    class Row:
        key_points_json = json.dumps(["好的", 42, None])

    assert _key_points(Row()) == ["好的"]


# --- an older database ----------------------------------------------------------


def test_an_older_database_gains_the_key_points_column(tmp_path, monkeypatch) -> None:
    """A Phase 10.11 install has no key_points_json; opening it must still work."""
    db_path = tmp_path / "old-key-points.db"
    connection = sqlite3.connect(db_path)
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
                content_quality VARCHAR(16) DEFAULT '',
                content_fetched_at DATETIME,
                created_at DATETIME,
                updated_at DATETIME
            );
            """
        )
        connection.execute(
            "INSERT INTO news_articles (id, title_cn, title_original, source, source_type,"
            " published_at, url, canonical_url, importance_score)"
            " VALUES ('rss-legacy', '旧标题', 'Old title', 'Cohere', 'official',"
            " '2026-09-14 02:00:00', 'https://example.com/legacy',"
            " 'https://example.com/legacy', 70)"
        )
        connection.commit()
    finally:
        connection.close()

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    configure_database(f"sqlite:///{db_path.as_posix()}")
    try:
        init_db()
        session = new_session()
        try:
            columns = {
                row[1]
                for row in session.execute(text("PRAGMA table_info(news_articles)")).fetchall()
            }
            item = NewsRepository(session).get_detail("rss-legacy")
        finally:
            session.close()
    finally:
        reset_database()

    assert "key_points_json" in columns
    # The row predates the field, so it reads back as "no bullets" rather than
    # NULL leaking into the API shape.
    assert item is not None
    assert item.key_points == []


# --- the API --------------------------------------------------------------------


def test_the_detail_response_carries_the_key_points(client: TestClient) -> None:
    store(article("rss-api-points", key_points=POINTS))

    payload = client.get("/api/v1/news/rss-api-points").json()

    assert payload["key_points"] == POINTS


def test_an_article_without_points_returns_an_empty_list_not_a_missing_key(
    client: TestClient,
) -> None:
    """A client may index the field unconditionally, so it is always present."""
    store(article("rss-api-empty"))

    payload = client.get("/api/v1/news/rss-api-empty").json()

    assert payload["key_points"] == []


def test_the_digest_and_favourites_shapes_also_carry_key_points(client: TestClient) -> None:
    from app.services.digest_store import DigestStore
    from tests.conftest import FROZEN_NOW, day_feeds, make_fixture_fetch

    DigestStore().refresh(now=FROZEN_NOW, fetch_text=make_fixture_fetch(*day_feeds("2026-09-11")))
    news_id = client.get("/api/v1/daily/2026-09-11").json()["news"][0]["id"]

    for item in client.get("/api/v1/daily/2026-09-11").json()["news"]:
        assert "key_points" in item

    client.post("/api/v1/favorites", json={"item_type": "news", "item_id": news_id})
    favourites = client.get("/api/v1/favorites").json()

    assert all("key_points" in favourite["item"] for favourite in favourites)


def test_the_search_shape_is_unchanged_by_the_new_field(client: TestClient) -> None:
    """Search has its own lightweight row shape and nothing was added to it."""
    client.get("/api/v1/search", params={"q": "anything"})

    payload = client.get("/api/v1/search", params={"q": "anything"}).json()

    assert set(payload) == {"query", "total", "items"}


# --- the prompt -----------------------------------------------------------------


def test_the_prompt_version_moved_so_old_summaries_are_not_reused() -> None:
    """A cached v2 summary has no key_points and must not satisfy a v3 article."""
    assert PROMPT_VERSION == "v3"


def test_the_prompt_defines_key_points_and_the_longer_summary() -> None:
    assert "key_points" in SYSTEM_PROMPT
    assert "150 到 300" in SYSTEM_PROMPT
    assert "100 到 200" in SYSTEM_PROMPT


def test_the_prompt_asks_for_the_non_marketing_five_questions() -> None:
    for phrase in ("谁发布", "与过去相比", "开源", "性能数据"):
        assert phrase in SYSTEM_PROMPT, phrase


def test_the_prompt_still_forbids_inventing_facts() -> None:
    # The Phase 10.5 grounding rules survive the rewrite.
    assert "不得补充正文中不存在的事实" in SYSTEM_PROMPT
    assert "不得根据你的模型记忆" in SYSTEM_PROMPT
    assert "改变整个 AI 行业" in SYSTEM_PROMPT


@pytest.mark.parametrize("word", ["夸张", "营销"])
def test_the_prompt_bans_hype_wording(word: str) -> None:
    assert word in SYSTEM_PROMPT
