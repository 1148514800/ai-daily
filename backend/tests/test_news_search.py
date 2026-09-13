"""Phase 10.9: full-text search over every stored article."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db.repositories import DigestRepository, NewsRepository
from app.db.session import new_session
from app.jobs.rebuild_search_index import rebuild
from app.models import NewsCategory, NewsItem
from app.services import news_search
from app.services.news_search import (
    BACKEND_LIKE,
    MAX_LIMIT,
    build_snippet,
    clamp_limit,
    ensure_index,
    query_tokens,
    rebuild_index,
    search_articles,
    search_backend,
)
from tests.conftest import FROZEN_NOW, day_feeds, make_fixture_fetch

UTC = timezone.utc


def article(
    news_id: str,
    *,
    title_cn: str = "",
    title_original: str = "",
    summary: str = "",
    why_it_matters: str = "",
    source: str = "OpenAI",
    published_at: datetime | None = None,
    body: str = "",
) -> NewsItem:
    return NewsItem(
        id=news_id,
        title_cn=title_cn,
        title_original=title_original,
        summary=summary,
        why_it_matters=why_it_matters,
        source=source,
        source_type="official",
        published_at=(published_at or datetime(2026, 9, 10, 4, 0, tzinfo=UTC)).isoformat(),
        category=NewsCategory.highlight,
        tags=[source],
        url=f"https://example.com/{news_id}",
        content_original=body,
    )


def corpus() -> list[NewsItem]:
    return [
        article(
            "rss-chinese-body",
            title_cn="某公司发布新模型",
            title_original="A company ships a model",
            summary="这是一段与关键词无关的摘要",
            body="我们讨论了强化学习方法在机器人上的应用，效果显著。",
        ),
        article(
            "rss-chinese-title",
            title_cn="DeepSeek 发布 V4.1",
            title_original="DeepSeek ships V4.1",
            summary="DeepSeek 正式发布 V4.1 Flash 模型，并宣布开源。",
            body="DeepSeek 正式发布 V4.1 Flash 模型。",
            source="DeepSeek",
        ),
        article(
            "rss-english-body",
            title_cn="Anthropic 发布安全报告",
            title_original="Anthropic safety report",
            summary="Anthropic published an alignment report.",
            body="Anthropic safety team published a new alignment report today.",
            source="Anthropic",
        ),
        article(
            "rss-openai",
            title_cn="OpenAI 发布 GPT-6",
            title_original="OpenAI ships GPT-6 Astra",
            summary="OpenAI released a new model.",
            body="OpenAI releases GPT-6 Astra with better reasoning abilities.",
            source="OpenAI",
        ),
    ]


def seed(items: list[NewsItem] | None = None) -> None:
    session = new_session()
    try:
        NewsRepository(session).upsert_many(items or corpus())
        session.commit()
    finally:
        session.close()


def find(query: str, **kwargs) -> list[str]:
    session = new_session()
    try:
        return [hit.news_id for hit in search_articles(session, query, **kwargs).items]
    finally:
        session.close()


def find_all(query: str, **kwargs):
    session = new_session()
    try:
        return search_articles(session, query, **kwargs)
    finally:
        session.close()


# --- field coverage ----------------------------------------------------------


def test_chinese_title_matches() -> None:
    seed()
    assert "rss-chinese-title" in find("DeepSeek")


def test_chinese_body_matches() -> None:
    seed()
    # The term exists only in content_original, in Chinese.
    assert find("强化学习") == ["rss-chinese-body"]


def test_english_title_matches() -> None:
    seed()
    assert "rss-openai" in find("GPT-6")


def test_english_body_matches() -> None:
    seed()
    assert find("reasoning") == ["rss-openai"]


def test_source_matches() -> None:
    seed()
    assert find("Anthropic") == ["rss-english-body"]


def test_summary_matches() -> None:
    seed()
    assert "rss-chinese-title" in find("开源")


def test_why_it_matters_matches() -> None:
    seed(
        [
            article(
                "rss-wim",
                title_cn="标题",
                why_it_matters="这会影响监管政策走向",
            )
        ]
    )
    assert find("监管政策") == ["rss-wim"]


def test_topic_matches() -> None:
    seed([article("rss-topic", title_cn="OpenAI 发布 GPT-6 模型")])
    # "model_release" is a derived label, so it is only reachable if the topic
    # was indexed alongside the article text.
    assert find("model_release") == ["rss-topic"]


def test_company_matches() -> None:
    seed([article("rss-company", title_cn="OpenAI 发布 GPT-6 模型", source="TechCrunch AI")])
    assert find("OpenAI") == ["rss-company"]


# --- relevance ---------------------------------------------------------------


def test_title_hit_outranks_body_only_hit() -> None:
    seed(
        [
            article("rss-body-only", title_cn="无关标题", body="这里有 DeepSeek 一段"),
            article("rss-title", title_cn="DeepSeek 发布新版本", body="正文"),
        ]
    )
    assert find("DeepSeek") == ["rss-title", "rss-body-only"]


def test_unrelated_articles_are_not_returned() -> None:
    seed()
    assert find("zzzz-no-result-test") == []


def test_search_ignores_importance_score() -> None:
    """Search relevance is not the daily ranking."""
    high = article("rss-high", title_cn="无关内容", body="")
    high.importance_score = 100
    low = article("rss-low", title_cn="Kubernetes 运维", body="Kubernetes")
    low.importance_score = 1
    seed([high, low])
    # Only the genuinely matching article comes back, whatever its importance.
    assert find("Kubernetes") == ["rss-low"]


# --- snippet -----------------------------------------------------------------


def test_snippet_is_centred_on_the_match() -> None:
    filler = "前面铺垫" * 30
    seed([article("rss-hit", title_cn="标题", body=f"{filler}DeepSeek 正式发布，随后结束。")])
    hit = find_all("DeepSeek").items[0]

    assert "DeepSeek" in hit.snippet
    assert hit.snippet.startswith("…")


def test_snippet_is_plain_text() -> None:
    """Stored bodies are already cleaned text, so a snippet is plain text too.

    The excerpt must not introduce markup or line breaks of its own: it is
    handed to the client as a single string and rendered as-is.
    """
    seed(
        [
            article(
                "rss-html",
                title_cn="标题",
                body="第一段 DeepSeek 介绍\n\n第二段 与命中无关的内容",
            )
        ]
    )
    snippet = find_all("DeepSeek").items[0].snippet

    assert "DeepSeek" in snippet
    assert "\n" not in snippet
    assert "<" not in snippet and ">" not in snippet


def test_snippet_marks_where_it_was_cut() -> None:
    """A trimmed excerpt says so; a whole short text is not decorated."""
    filler = "铺垫" * 80
    seed([article("rss-trim", title_cn="标题", body=f"{filler} DeepSeek 结尾")])
    trimmed = find_all("DeepSeek").items[0].snippet
    assert trimmed.startswith("…")

    seed([article("rss-short", title_cn="短 DeepSeek 文本", body="")])
    whole = find_all("短 DeepSeek").items[0].snippet
    assert not whole.startswith("…")


def test_snippet_is_short() -> None:
    seed([article("rss-long", title_cn="标题", body="DeepSeek " + "很长的段落 " * 200)])
    assert len(find_all("DeepSeek").items[0].snippet) <= 200


def test_snippet_skips_a_summary_that_lacks_the_term() -> None:
    """The excerpt must be about the match, not the first thing stored."""
    seed(
        [
            article(
                "rss-pick",
                title_cn="标题",
                summary="这段摘要完全没有那个词",
                body="正文里提到了 DeepSeek，所以应该从正文取。",
            )
        ]
    )
    snippet = find_all("DeepSeek").items[0].snippet

    assert "DeepSeek" in snippet
    assert "这段摘要完全没有那个词" not in snippet


def test_build_snippet_handles_missing_text_and_terms() -> None:
    assert build_snippet("", ["x"]) == ""
    assert build_snippet(None, ["x"]) == ""
    # No term present: still give context rather than an empty string.
    assert build_snippet("一段没有命中词的文字", ["nope"]) != ""


# --- API payload -------------------------------------------------------------


def test_search_never_returns_the_article_body(client) -> None:
    seed([article("rss-body", title_cn="标题", body="DeepSeek 的完整正文内容")])
    payload = client.get("/api/v1/search", params={"q": "DeepSeek"}).json()

    assert payload["items"]
    for row in payload["items"]:
        assert "content_original" not in row
        assert "content_language" not in row


def test_detail_still_returns_the_body(client) -> None:
    seed([article("rss-body", title_cn="标题", body="DeepSeek 的完整正文内容")])
    detail = client.get("/api/v1/news/rss-body").json()

    assert detail["content_original"] == "DeepSeek 的完整正文内容"


def test_search_api_shape(client) -> None:
    seed()
    payload = client.get("/api/v1/search", params={"q": "DeepSeek"}).json()

    assert payload["query"] == "DeepSeek"
    assert payload["total"] >= 1
    row = next(r for r in payload["items"] if r["news_id"] == "rss-chinese-title")
    assert row["source"] == "DeepSeek"
    assert row["topic"]
    assert row["company"]
    assert row["digest_date"] is None
    # Same timestamp shape as the digest endpoints, not SQLite's own format.
    assert row["published_at"] == "2026-09-10T04:00:00+00:00"


def test_search_reports_the_digest_date(client) -> None:
    seed()
    DigestRepository_digest("2026-09-10", ["rss-chinese-title"])

    row = next(
        r
        for r in client.get("/api/v1/search", params={"q": "DeepSeek"}).json()["items"]
        if r["news_id"] == "rss-chinese-title"
    )
    assert row["digest_date"] == "2026-09-10"


def DigestRepository_digest(date: str, news_ids: list[str]) -> None:
    session = new_session()
    try:
        DigestRepository(session).save(
            date=date, title="t", description="", news_ids=news_ids, github_ids=[]
        )
        session.commit()
    finally:
        session.close()


def test_future_article_has_no_digest_date(client) -> None:
    """An article ahead of every window is searchable but undated by digest."""
    seed([article("rss-future", title_cn="未来文章 DeepSeek", published_at=datetime(2026, 9, 20, 0, 0, tzinfo=UTC))])

    row = client.get("/api/v1/search", params={"q": "DeepSeek"}).json()["items"][0]
    assert row["news_id"] == "rss-future"
    assert row["digest_date"] is None


# --- paging and limits -------------------------------------------------------


def test_limit_and_offset_page_through_results(client) -> None:
    seed([article(f"rss-{i:02d}", title_cn=f"DeepSeek 第 {i} 条") for i in range(5)])
    first = client.get("/api/v1/search", params={"q": "DeepSeek", "limit": 2}).json()
    second = client.get("/api/v1/search", params={"q": "DeepSeek", "limit": 2, "offset": 2}).json()

    assert first["total"] == 5
    assert len(first["items"]) == 2
    assert len(second["items"]) == 2
    assert {r["news_id"] for r in first["items"]} & {r["news_id"] for r in second["items"]} == set()


def test_limit_is_capped(client) -> None:
    assert client.get("/api/v1/search", params={"q": "x", "limit": 500}).status_code == 422
    assert client.get("/api/v1/search", params={"q": "x", "limit": MAX_LIMIT}).status_code == 200
    assert clamp_limit(9999) == MAX_LIMIT


def test_limit_below_one_is_rejected(client) -> None:
    assert client.get("/api/v1/search", params={"q": "x", "limit": 0}).status_code == 422


def test_negative_offset_is_rejected(client) -> None:
    assert client.get("/api/v1/search", params={"q": "x", "offset": -1}).status_code == 422


def test_empty_query_returns_an_empty_result_not_an_error(client) -> None:
    seed()
    for params in ({}, {"q": ""}, {"q": "   "}):
        response = client.get("/api/v1/search", params=params)
        assert response.status_code == 200
        assert response.json() == {"query": response.json()["query"], "total": 0, "items": []}


def test_missing_query_does_not_dump_the_archive(client) -> None:
    seed()
    assert client.get("/api/v1/search").json()["items"] == []


# --- query safety ------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    ['"', "'", "-", "(", ")", "*", ":", "a:b", "(x)", "it's", "DeepSeek -", "C++", "\\", "%", "_", "&&", "NOT", "AND OR", '"unclosed'],
)
def test_special_characters_never_break_search(client, query: str) -> None:
    seed()
    response = client.get("/api/v1/search", params={"q": query})

    assert response.status_code == 200
    assert isinstance(response.json()["items"], list)


def test_like_wildcards_are_literal_not_interpolated() -> None:
    """`%` and `_` must match themselves, not act as LIKE wildcards."""
    seed(
        [
            article("rss-plain", title_cn="普通标题 DeepSeek", body=""),
            article("rss-percent", title_cn="100% 覆盖率的进展", body=""),
        ]
    )
    # If "%" were treated as a wildcard this would match every article.
    assert find("%") == ["rss-percent"]
    # Underscore is likewise literal: it matches the derived topic
    # "model_release", which really does contain one, and not everything else.
    assert find("_") == ["rss-plain"]
    assert find("model_release") == ["rss-plain"]


def test_query_tokens_split_limit_and_deduplicate() -> None:
    assert query_tokens("  DeepSeek   Agent ") == ["DeepSeek", "Agent"]
    assert query_tokens("a a a") == ["a"]
    assert query_tokens("") == []
    assert query_tokens(None) == []
    assert len(query_tokens(" ".join(f"t{i}" for i in range(50)))) <= news_search.MAX_TOKENS


def test_multi_term_query_requires_all_terms() -> None:
    seed()
    assert find("Anthropic safety") == ["rss-english-body"]
    # "Anthropic" appears, "Kubernetes" does not: no result.
    assert find("Anthropic Kubernetes") == []


# --- two-character Chinese ---------------------------------------------------


def test_two_character_chinese_is_still_searchable() -> None:
    """A trigram cannot represent two characters, so these go through LIKE."""
    seed([article("rss-model", title_cn="新的 模型 发布", body="正文")])
    assert find("模型") == ["rss-model"]


def test_two_character_chinese_narrows_instead_of_matching_everything() -> None:
    seed([article("rss-two", title_cn="模型 讨论", body=""), article("rss-other", title_cn="无关内容", body="")])
    assert find("模型") == ["rss-two"]


# --- index maintenance -------------------------------------------------------


def test_new_article_becomes_searchable_after_write(client) -> None:
    seed()
    assert "rss-new" not in find("新收录关键词")
    seed([article("rss-new", title_cn="新收录关键词 出现")])
    assert find("新收录关键词") == ["rss-new"]


def test_updating_a_body_updates_the_index(client) -> None:
    seed([article("rss-update", title_cn="标题", body="")])
    assert find("后来补上的正文词") == []

    session = new_session()
    try:
        NewsRepository(session).set_content(
            "rss-update", content="后来补上的正文词", language="zh", method="web"
        )
        session.commit()
    finally:
        session.close()

    assert find("后来补上的正文词") == ["rss-update"]


def test_reindex_replaces_instead_of_duplicating() -> None:
    seed([article("rss-dup", title_cn="DeepSeek 一次", body="")])
    seed([article("rss-dup", title_cn="DeepSeek 两次", body="")])

    assert find("DeepSeek") == ["rss-dup"]
    assert find_all("DeepSeek").total == 1


def test_rebuild_is_idempotent() -> None:
    seed()
    first = find("DeepSeek")
    session = new_session()
    try:
        assert rebuild_index(session).indexed == len(corpus())
        session.commit()
        second = [hit.news_id for hit in search_articles(session, "DeepSeek").items]
    finally:
        session.close()

    assert first == second


def test_rebuild_command_indexes_existing_articles() -> None:
    seed()
    stats = rebuild()

    assert stats.articles == len(corpus())
    assert stats.indexed == len(corpus())
    assert find("DeepSeek")


def test_rebuild_touches_no_digest_association() -> None:
    seed()
    DigestRepository_digest("2026-09-10", ["rss-chinese-title"])
    before = client_digest_ids("2026-09-10")

    rebuild()

    assert client_digest_ids("2026-09-10") == before


def client_digest_ids(date: str) -> list[str]:
    session = new_session()
    try:
        return DigestRepository(session).get_news_ids(date)
    finally:
        session.close()


def test_rebuild_never_deletes_articles() -> None:
    seed()
    rebuild()
    session = new_session()
    try:
        assert NewsRepository(session).count() == len(corpus())
    finally:
        session.close()


def test_articles_are_indexed_even_without_a_digest() -> None:
    """A stored article is searchable whether or not it reached a digest."""
    seed([article("rss-orphan", title_cn="没有日报的关键词 孤立")])
    assert find("孤立") == ["rss-orphan"]


def test_reading_search_never_collects(client, monkeypatch) -> None:
    seed()

    def fail(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("search must not collect")

    monkeypatch.setattr("app.collectors.rss.fetch_rss_text", fail)
    monkeypatch.setattr("app.collectors.html.fetch_html", fail)

    assert client.get("/api/v1/search", params={"q": "DeepSeek"}).status_code == 200


def test_column_mapping_keeps_source_and_body_apart() -> None:
    """Guards the index field order: source and body must not swap."""
    seed([article("rss-map", title_cn="标题", source="SourceMarker", body="BodyMarker")])
    session = new_session()
    try:
        row = session.execute(
            __import__("sqlalchemy").text(
                "SELECT source, content_original FROM news_search_fts WHERE news_id = 'rss-map'"
            )
        ).one()
    finally:
        session.close()

    assert row[0] == "SourceMarker"
    assert row[1] == "BodyMarker"


# --- backend detection and fallback -----------------------------------------


def test_a_backend_is_reported() -> None:
    session = new_session()
    try:
        assert search_backend(session) in {news_search.BACKEND_TRIGRAM, news_search.BACKEND_FTS5, BACKEND_LIKE}
    finally:
        session.close()


def test_missing_index_falls_back_to_like_without_failing() -> None:
    """No FTS table must still be searchable, via SQL LIKE."""
    seed()
    session = new_session()
    try:
        session.execute(__import__("sqlalchemy").text('DROP TABLE IF EXISTS "news_search_fts"'))
        session.commit()
        assert search_backend(session) == BACKEND_LIKE
        ids = [hit.news_id for hit in search_articles(session, "DeepSeek").items]
    finally:
        session.close()

    assert "rss-chinese-title" in ids


def test_like_fallback_still_orders_title_hits_first() -> None:
    seed(
        [
            article("rss-body-only", title_cn="无关标题", body="这里有 DeepSeek 一段"),
            article("rss-title", title_cn="DeepSeek 发布新版本", body="正文"),
        ]
    )
    session = new_session()
    try:
        session.execute(__import__("sqlalchemy").text('DROP TABLE IF EXISTS "news_search_fts"'))
        session.commit()
        ids = [hit.news_id for hit in search_articles(session, "DeepSeek").items]
    finally:
        session.close()

    assert ids[0] == "rss-title"


def test_app_startup_builds_the_index() -> None:
    """A database written before search existed becomes searchable at startup."""
    seed()
    session = new_session()
    try:
        # Simulate the pre-search state: articles present, index empty.
        session.execute(__import__("sqlalchemy").text('DROP TABLE IF EXISTS "news_search_fts"'))
        session.commit()
    finally:
        session.close()

    from app.db.session import get_engine

    stats = ensure_index(get_engine())
    assert stats.indexed == len(corpus())
    assert find("DeepSeek")


# --- no regressions ----------------------------------------------------------


def test_digest_endpoints_still_work(client) -> None:
    """Search must not disturb the digest reads it sits next to."""
    day_one = FROZEN_NOW
    day_two = day_one + timedelta(days=1)
    from app.services.digest_store import DigestStore

    DigestStore().refresh(now=day_one, fetch_text=make_fixture_fetch(*day_feeds("2026-09-11")))
    DigestStore().refresh(now=day_two, fetch_text=make_fixture_fetch(*day_feeds("2026-09-12")))

    assert client.get("/api/v1/digests").status_code == 200
    assert client.get("/api/v1/daily/2026-09-11").status_code == 200


def test_freshly_collected_news_is_searchable(client) -> None:
    from app.services.digest_store import DigestStore

    DigestStore().refresh(now=FROZEN_NOW, fetch_text=make_fixture_fetch(*day_feeds("2026-09-11")))
    payload = client.get("/api/v1/search", params={"q": "OpenAI story"}).json()

    assert payload["total"] >= 1


def test_favorites_still_work_with_a_search_hit(client) -> None:
    seed()
    hit = client.get("/api/v1/search", params={"q": "DeepSeek"}).json()["items"][0]
    created = client.post(
        "/api/v1/favorites", json={"item_type": "news", "item_id": hit["news_id"]}
    )

    assert created.status_code == 201
    assert created.json()["item"]["id"] == hit["news_id"]


def test_mobile_matches_the_backend_page_size_contract() -> None:
    """The client's own constants must stay inside this module's limits.

    The mobile unit tests cannot import Python, and the backend cannot import
    TypeScript, so the agreement is checked from one side. If either side is
    retuned on its own, this fails rather than the app silently sending a limit
    the API rejects with a 422.
    """
    import re
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "mobile" / "lib" / "search.ts").read_text(
        encoding="utf-8"
    )
    page_size = int(re.search(r"SEARCH_PAGE_SIZE\s*=\s*(\d+)", source).group(1))
    debounce = int(re.search(r"SEARCH_DEBOUNCE_MS\s*=\s*(\d+)", source).group(1))

    assert 0 < page_size <= MAX_LIMIT
    assert debounce > 0
