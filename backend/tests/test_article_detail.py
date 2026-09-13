"""Phase 10.5: the body through the pipeline, the database, and the API.

Extraction is only useful if it survives the whole path: collected article ->
grounded summary -> stored body -> detail response. These tests follow that
path and check that nothing regressed on the way: the issue window, the Phase
10.4 event dedup, and the same-day merge all still behave as before.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.collectors.http import FetchError, FetchResult
from app.db.repositories import NewsRepository
from app.db.session import configure_database, init_db, new_session, reset_database
from app.pipelines.normalize import stable_news_id
from app.services.digest_store import DigestStore, store
from app.services.llm.cache import LLMCache
from app.services.llm.client import LLMCompletion, LLMError
from app.services.llm.enrich import enrich_articles
from app.services.llm.prompts import PROMPT_VERSION
from app.services.llm.settings import LLMSettings
from tests.conftest import EMPTY_HTML, EMPTY_RSS, build_rss

UTC = timezone.utc

OPENAI_URL = "https://openai.com/index/gpt-6-astra"
QBITAI_URL = "https://www.qbitai.com/2026/09/reasoning"

OPENAI_BODY = (
    "OpenAI introduced a new reasoning mode today that lets the model spend more "
    "time on a problem before answering. The company says the mode is available "
    "in the API immediately and that it improves results on multi-step tasks. "
    "It also published evaluation numbers comparing the new mode with the "
    "previous default, and said pricing is unchanged for the first month. "
    "Engineers described the change as a shift in how the model allocates "
    "compute rather than a new model release, and said the same weights are "
    "used throughout. Early users reported better results on long multi-step "
    "tool use while simple prompts became slower, so the mode stays opt-in. "
    "A separate note said the older mode remains the default for now."
)

QBITAI_BODY = (
    "OpenAI 今天发布了新的推理模式，模型在回答之前会花更多时间思考问题。"
    "官方表示该模式已经可以在 API 中直接使用，并且在多步任务上的效果明显更好。"
    "公司同时公布了与旧默认模式的评测对比结果，并表示首月价格保持不变。"
    "团队工程师称这次变化改变的是模型分配算力的方式，并不是发布新模型，"
    "整个过程中使用的仍然是同一套权重参数。"
    "早期用户反馈称在长链路工具调用上效果更好，但简单问题的响应速度明显变慢，"
    "因此该模式目前仍然需要手动开启。"
    "另有说明表示，在收集到更多线上流量数据之前，旧模式将继续作为默认选项。"
)


def shanghai(day: str, hour: int, minute: int = 0) -> datetime:
    local = datetime.strptime(day, "%Y-%m-%d").replace(
        hour=hour, minute=minute, tzinfo=ZoneInfo("Asia/Shanghai")
    )
    return local.astimezone(UTC)


def page_html(body: str) -> str:
    paragraphs = "\n".join(f"<p>{chunk}</p>" for chunk in body.splitlines() if chunk.strip())
    return f"<html><body><article><h1>Headline</h1>{paragraphs}</article></body></html>"


def page(body: str) -> FetchResult:
    return FetchResult(
        url="https://example.com/a",
        status=200,
        content_type="text/html; charset=utf-8",
        text=page_html(body),
    )


def routing_fetch(feeds: dict[str, str], failing: set[str] | None = None):
    """Serve a named feed per source id, empty pages elsewhere."""
    from app.config.sources import enabled_sources

    offline = failing or set()
    routes: dict[str, tuple[str, str]] = {}
    for source in enabled_sources():
        payload = feeds.get(source.id, EMPTY_HTML.get(source.id, EMPTY_RSS) if source.kind == "html" else EMPTY_RSS)
        routes[source.url] = (source.id, payload)

    def fetch(url: str, timeout: float = 10.0) -> str:
        route = routes.get(url) or routes.get(url.rstrip("/")) or routes.get(url + "/")
        if route is None and url.startswith("https://api-docs.deepseek.com/"):
            route = ("deepseek", EMPTY_HTML["deepseek"])
        if route is None:
            raise FetchError(f"unknown source {url}")
        source_id, payload = route
        if source_id in offline:
            raise FetchError(f"{source_id} offline")
        return payload

    return fetch


# --- 16. the LLM summary is grounded in the body ---


class RecordingClient:
    def __init__(self, payload: dict | None = None, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error
        self.messages: list[list[dict[str, str]]] = []

    def complete(self, messages: list[dict[str, str]]) -> LLMCompletion:
        self.messages.append(messages)
        if self.error is not None:
            raise self.error
        return LLMCompletion(text=json.dumps(self.payload, ensure_ascii=False))


def llm_settings(tmp_path: Path) -> LLMSettings:
    return LLMSettings(
        enabled=True,
        api_key="k",
        model="m",
        base_url="https://example.invalid/v1",
        timeout=5.0,
        cache_dir=tmp_path / "llm-cache",
    )


def test_prompt_sends_the_body_and_forbids_outside_facts(tmp_path: Path) -> None:
    from app.collectors.raw import RawArticle
    from app.pipelines.urls import canonicalize_url

    raw = RawArticle(
        source_id="openai",
        source="OpenAI",
        source_type="official",
        title="Headline",
        url=OPENAI_URL,
        canonical_url=canonicalize_url(OPENAI_URL),
        published_at=datetime(2026, 9, 13, 6, 0, tzinfo=UTC),
        summary="short teaser",
        feed_body=f"<p>{OPENAI_BODY}</p>",
        content=OPENAI_BODY,
        content_language="en",
        content_method="web",
    )
    client = RecordingClient(
        {
            "title_cn": "OpenAI 发布新推理模式",
            "summary_cn": "OpenAI 在 API 中上线新的推理模式。",
            "why_it_matters": "长任务效果更好。",
            "importance_score": 80,
        }
    )

    items, stats = enrich_articles(
        [raw],
        settings=llm_settings(tmp_path),
        cache=LLMCache(tmp_path / "llm-cache"),
        client=client,
    )

    assert stats.success == 1
    user_prompt = client.messages[0][1]["content"]
    system_prompt = client.messages[0][0]["content"]
    # The model is given the body, not just the teaser.
    assert OPENAI_BODY[:120] in user_prompt
    assert "content_language: en" in user_prompt
    # And it is told not to invent anything beyond that body.
    assert "不得补充正文中不存在的事实" in system_prompt
    assert items[0].summary == "OpenAI 在 API 中上线新的推理模式。"


def test_long_body_is_trimmed_for_the_prompt_only(tmp_path: Path) -> None:
    from app.collectors.raw import RawArticle
    from app.pipelines.urls import canonicalize_url

    huge = OPENAI_BODY * 60
    raw = RawArticle(
        source_id="openai",
        source="OpenAI",
        source_type="official",
        title="Headline",
        url=OPENAI_URL,
        canonical_url=canonicalize_url(OPENAI_URL),
        published_at=datetime(2026, 9, 13, 6, 0, tzinfo=UTC),
        summary="teaser",
        content=huge,
        content_language="en",
    )
    client = RecordingClient(
        {"title_cn": "t", "summary_cn": "s", "why_it_matters": "", "importance_score": 50}
    )
    settings = replace(llm_settings(tmp_path), content_max_chars=400)

    items, _ = enrich_articles(
        [raw], settings=settings, cache=LLMCache(tmp_path / "llm-cache"), client=client
    )

    prompt = client.messages[0][1]["content"]
    assert len(prompt) < len(huge)
    # The item keeps the full body; only the prompt was trimmed.
    assert items[0].content_original == huge


def test_extraction_failure_uses_the_rss_summary_in_the_prompt(tmp_path: Path) -> None:
    from app.collectors.raw import RawArticle
    from app.pipelines.urls import canonicalize_url

    raw = RawArticle(
        source_id="openai",
        source="OpenAI",
        source_type="official",
        title="Headline",
        url=OPENAI_URL,
        canonical_url=canonicalize_url(OPENAI_URL),
        published_at=datetime(2026, 9, 13, 6, 0, tzinfo=UTC),
        summary="A short RSS teaser.",
        content="",
        content_language="",
    )
    client = RecordingClient(
        {"title_cn": "t", "summary_cn": "s", "why_it_matters": "", "importance_score": 50}
    )

    enrich_articles([raw], settings=llm_settings(tmp_path), cache=LLMCache(tmp_path / "llm-cache"), client=client)

    prompt = client.messages[0][1]["content"]
    assert "rss_summary: A short RSS teaser." in prompt
    assert "正文抓取失败" in prompt


# --- 17. an LLM failure still leaves the original article readable ---


def test_llm_failure_keeps_the_original_body(tmp_path: Path) -> None:
    from app.collectors.raw import RawArticle
    from app.pipelines.urls import canonicalize_url

    raw = RawArticle(
        source_id="openai",
        source="OpenAI",
        source_type="official",
        title="Headline",
        url=OPENAI_URL,
        canonical_url=canonicalize_url(OPENAI_URL),
        published_at=datetime(2026, 9, 13, 6, 0, tzinfo=UTC),
        summary="teaser",
        content=OPENAI_BODY,
        content_language="en",
        content_method="web",
    )
    client = RecordingClient(error=LLMError("boom"))

    items, stats = enrich_articles(
        [raw], settings=llm_settings(tmp_path), cache=LLMCache(tmp_path / "llm-cache"), client=client
    )

    assert stats.failed == 1
    assert items[0].content_original == OPENAI_BODY
    assert items[0].content_language == "en"


# --- the whole path through a refresh ---


def write_page(directory: Path, name: str, body: str) -> str:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(page_html(body), encoding="utf-8")
    return (directory / name).read_text(encoding="utf-8")


def test_refresh_stores_the_original_body_and_serves_it_from_the_detail_api(tmp_path, monkeypatch) -> None:
    """Collect -> window -> dedupe -> extract -> enrich -> persist -> API."""
    moment = shanghai("2026-09-13", 8)
    feeds = {
        "openai": build_rss([("New reasoning mode", OPENAI_URL, shanghai("2026-09-13", 6))]),
        "qbitai": build_rss([("新的推理模式", QBITAI_URL, shanghai("2026-09-13", 5))]),
    }
    pages = {OPENAI_URL: page_html(OPENAI_BODY), QBITAI_URL: page_html(QBITAI_BODY)}
    monkeypatch.setenv("ARTICLE_CACHE_DIR", str(tmp_path / "article-cache"))

    def fetch_page(url: str, *, timeout: float = 10.0):
        if url not in pages:
            raise FetchError("HTTP 404", status=404)
        return FetchResult(url=url, status=200, content_type="text/html", text=pages[url])

    events = DigestStore()
    events.refresh(now=moment, fetch_text=routing_fetch(feeds), fetch_page=fetch_page)

    session = new_session()
    try:
        openai = NewsRepository(session).get_detail(stable_news_id(OPENAI_URL))
        chinese = NewsRepository(session).get_detail(stable_news_id(QBITAI_URL))
    finally:
        session.close()

    assert openai is not None and chinese is not None
    # Original language is preserved on both sides.
    assert openai.content_language == "en"
    assert OPENAI_BODY in openai.content_original
    assert chinese.content_language == "zh"
    assert QBITAI_BODY in chinese.content_original
    assert events.last_extraction_stats.web == 2


def test_detail_endpoint_returns_body_and_the_list_does_not(tmp_path, monkeypatch) -> None:
    moment = shanghai("2026-09-13", 8)
    feeds = {"openai": build_rss([("New reasoning mode", OPENAI_URL, shanghai("2026-09-13", 6))])}
    monkeypatch.setenv("ARTICLE_CACHE_DIR", str(tmp_path / "article-cache"))

    def fetch_page(url: str, *, timeout: float = 10.0):
        if url == OPENAI_URL:
            return FetchResult(url=url, status=200, content_type="text/html", text=page_html(OPENAI_BODY))
        raise FetchError("HTTP 404", status=404)

    DigestStore().refresh(now=moment, fetch_text=routing_fetch(feeds), fetch_page=fetch_page)

    from app.main import app

    news_id = stable_news_id(OPENAI_URL)
    with TestClient(app) as client:
        detail = client.get(f"/api/v1/news/{news_id}")
        digest = client.get("/api/v1/daily/2026-09-13")

    assert detail.status_code == 200
    payload = detail.json()
    assert OPENAI_BODY in payload["content_original"]
    assert payload["content_language"] == "en"
    # Backward compatible: every list field is still present.
    for field in ("id", "title_cn", "title_original", "summary", "why_it_matters", "url", "source"):
        assert field in payload
    # The list response stays lean.
    listed = digest.json()["news"][0]
    assert "content_original" not in listed


def test_detail_api_404_for_an_unknown_article(client) -> None:
    assert client.get("/api/v1/news/nope").status_code == 404


# --- 21/22. no regression in the window or the same-day merge ---


def test_issue_window_still_decides_membership(tmp_path, monkeypatch) -> None:
    moment = shanghai("2026-09-13", 8)
    feeds = {
        "openai": build_rss(
            [
                ("Inside", "https://openai.com/index/inside", shanghai("2026-09-13", 7)),
                ("Future", "https://openai.com/index/future", shanghai("2026-09-14", 5)),
                ("Too old", "https://openai.com/index/old", shanghai("2026-09-10", 7)),
            ]
        )
    }
    monkeypatch.setenv("ARTICLE_CACHE_DIR", str(tmp_path / "article-cache"))

    DigestStore().refresh(
        now=moment,
        fetch_text=routing_fetch(feeds),
        fetch_page=lambda url, timeout=10.0: (_ for _ in ()).throw(FetchError("offline")),
    )

    digest = store.get_digest("2026-09-13")
    titles = {item.title_original for item in digest.news}
    assert titles == {"Inside"}


def test_same_day_second_refresh_keeps_the_first_body(tmp_path, monkeypatch) -> None:
    morning = shanghai("2026-09-13", 8)
    evening = shanghai("2026-09-13", 18)
    first_feeds = {"openai": build_rss([("First", "https://openai.com/index/first", shanghai("2026-09-13", 7))])}
    second_feeds = {"openai": build_rss([("Second", "https://openai.com/index/second", shanghai("2026-09-13", 12))])}
    monkeypatch.setenv("ARTICLE_CACHE_DIR", str(tmp_path / "article-cache"))

    def fetch_page(url: str, *, timeout: float = 10.0):
        body = OPENAI_BODY if url.endswith("first") else QBITAI_BODY
        return FetchResult(url=url, status=200, content_type="text/html", text=page_html(body))

    store_ = DigestStore()
    store_.refresh(now=morning, fetch_text=routing_fetch(first_feeds), fetch_page=fetch_page)
    store_.refresh(now=evening, fetch_text=routing_fetch(second_feeds), fetch_page=fetch_page)

    digest = store.get_digest("2026-09-13")
    assert {item.title_original for item in digest.news} == {"First", "Second"}
    ids = [item.id for item in digest.news]
    assert len(ids) == len(set(ids))
    # Both bodies survive the merge.
    assert all(item.content_original for item in digest.news)
    assert store_.last_extraction_stats.cache_hits == 0


def test_repeated_refresh_reuses_the_cached_body(tmp_path, monkeypatch) -> None:
    moment = shanghai("2026-09-13", 8)
    feeds = {"openai": build_rss([("Story", "https://openai.com/index/story", shanghai("2026-09-13", 7))])}
    monkeypatch.setenv("ARTICLE_CACHE_DIR", str(tmp_path / "article-cache"))
    calls: list[str] = []

    def fetch_page(url: str, *, timeout: float = 10.0):
        calls.append(url)
        return FetchResult(url=url, status=200, content_type="text/html", text=page_html(OPENAI_BODY))

    store_ = DigestStore()
    store_.refresh(now=moment, fetch_text=routing_fetch(feeds), fetch_page=fetch_page)
    store_.refresh(now=moment + timedelta(minutes=1), fetch_text=routing_fetch(feeds), fetch_page=fetch_page)

    assert len(calls) == 1
    assert store_.last_extraction_stats.cache_hits == 1


def test_one_source_failure_does_not_stop_extraction(tmp_path, monkeypatch) -> None:
    moment = shanghai("2026-09-13", 8)
    feeds = {
        "openai": build_rss([("Story", OPENAI_URL, shanghai("2026-09-13", 7))]),
        "nvidia": build_rss([("Other", "https://blogs.nvidia.com/other", shanghai("2026-09-13", 6))]),
    }
    monkeypatch.setenv("ARTICLE_CACHE_DIR", str(tmp_path / "article-cache"))

    def fetch_page(url: str, *, timeout: float = 10.0):
        return FetchResult(url=url, status=200, content_type="text/html", text=page_html(OPENAI_BODY))

    store_ = DigestStore()
    store_.refresh(
        now=moment,
        fetch_text=routing_fetch(feeds, failing={"nvidia"}),
        fetch_page=fetch_page,
    )

    digest = store.get_digest("2026-09-13")
    assert {item.title_original for item in digest.news} == {"Story"}
    assert store_.last_extraction_stats.web == 1


# --- 20. Phase 10.4 event dedup still folds cross-source duplicates ---


def test_event_dedup_still_merges_cross_source_duplicates(tmp_path, monkeypatch) -> None:
    """Two sources, one release: the digest still links a single entry.

    Enrichment is off in tests, so the Chinese summaries are seeded into the LLM
    cache the way a real refresh would have produced them: two outlets
    paraphrasing one release in near-identical Chinese. That is the case Phase
    10.4's event dedup exists for, and it must still fold them after Phase 10.5
    inserted extraction into the pipeline.
    """
    moment = shanghai("2026-09-13", 8)
    techcrunch_url = "https://techcrunch.com/2026/09/13/astra"
    feeds = {
        "openai": build_rss([("Introducing GPT-6 Astra", OPENAI_URL, shanghai("2026-09-13", 6))]),
        "techcrunch-ai": build_rss(
            [("OpenAI launches GPT-6 Astra, a new frontier model", techcrunch_url, shanghai("2026-09-13", 6, 30))]
        ),
    }
    monkeypatch.setenv("ARTICLE_CACHE_DIR", str(tmp_path / "article-cache"))
    seed_enrichment_cache(
        tmp_path,
        monkeypatch,
        {
            OPENAI_URL: "Introducing GPT-6 Astra",
            techcrunch_url: "OpenAI launches GPT-6 Astra, a new frontier model",
        },
    )

    def fetch_page(url: str, *, timeout: float = 10.0):
        # Extraction is not what this test is about: the body is unavailable, so
        # the seeded cache entry (keyed on the same empty body) is what enrichment
        # reads, exactly as Phase 10.4's own tests arrange it.
        raise FetchError("offline")

    store_ = DigestStore()
    store_.refresh(now=moment, fetch_text=routing_fetch(feeds), fetch_page=fetch_page)

    assert store_.last_event_stats.candidates == 2
    assert store_.last_event_stats.merged == 1
    assert len(store.get_digest("2026-09-13").news) == 1


def seed_enrichment_cache(
    tmp_path: Path,
    monkeypatch,
    titles: dict[str, str],
) -> None:
    """Pre-fill the LLM cache so two sources look like one Chinese event.

    The key mirrors ``enrich._cache_key`` exactly, including the prompt version,
    so this seeds the same entry a real run would read.
    """
    from app.models import NewsCategory, NewsItem
    from app.pipelines.urls import canonicalize_url
    from app.services.llm.prompts import PROMPT_VERSION
    from app.services.llm.schemas import ArticleEnrichment
    from app.services.llm.settings import load_llm_settings

    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path / "llm-cache"))
    settings = load_llm_settings()
    cache = LLMCache(settings.cache_dir)
    for url, title in titles.items():
        summary = ""
        key = cache.make_key(
            canonical_url=canonicalize_url(url),
            title=title,
            summary=summary,
            model=settings.model,
            prompt_version=PROMPT_VERSION,
        )
        cache.set(
            key,
            ArticleEnrichment(
                title_cn="OpenAI 发布 GPT-6 Astra 新模型",
                summary_cn="面向企业长任务的前沿模型，支持长程 agentic 工作。",
                why_it_matters="面向企业长任务的前沿模型。",
                importance_score=88,
            ),
        )


# --- 18. an older SQLite file is upgraded in place ---


def test_old_sqlite_database_gains_the_content_columns(tmp_path, monkeypatch) -> None:
    """A database written before Phase 10.5 must open and gain the new columns."""
    from sqlalchemy import create_engine, text

    db_path = tmp_path / "old.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE news_articles ("
                "id VARCHAR(64) PRIMARY KEY, title_cn TEXT, title_original TEXT, "
                "summary TEXT, why_it_matters TEXT, source VARCHAR(128), "
                "source_type VARCHAR(64), published_at DATETIME, "
                "category VARCHAR(32), url TEXT, canonical_url TEXT, "
                "importance_score INTEGER, created_at DATETIME, updated_at DATETIME)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO news_articles (id, title_cn, title_original, summary, url) "
                "VALUES ('rss-old', '标题', 'Title', '摘要', 'https://example.com/a')"
            )
        )
    engine.dispose()

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    configure_database(f"sqlite:///{db_path.as_posix()}")
    try:
        init_db()
        session = new_session()
        try:
            migrated = session.execute(text("PRAGMA table_info(news_articles)")).fetchall()
            columns = {row[1] for row in migrated}
            # The pre-existing row is intact and readable through the new model.
            item = NewsRepository(session).get_detail("rss-old")
        finally:
            session.close()
        assert {"content_original", "content_language", "content_extraction_method", "content_fetched_at"} <= columns
        assert item is not None
        assert item.title_original == "Title"
        assert item.content_original == ""
    finally:
        reset_database()


def test_a_new_body_is_not_overwritten_by_an_empty_refresh(tmp_path) -> None:
    """A refresh whose extraction failed must not erase a stored body."""
    from app.models import NewsCategory, NewsItem

    session = new_session()
    try:
        repository = NewsRepository(session)
        repository.upsert_many(
            [
                NewsItem(
                    id="rss-keep",
                    title_cn="标题",
                    title_original="Title",
                    summary="摘要",
                    why_it_matters="",
                    source="OpenAI",
                    source_type="official",
                    published_at="2026-09-13T06:00:00+00:00",
                    category=NewsCategory.highlight,
                    tags=["OpenAI"],
                    url="https://openai.com/index/keep",
                    content_original=OPENAI_BODY,
                    content_language="en",
                    content_extraction_method="web",
                    content_fetched_at="2026-09-13T08:00:00+00:00",
                )
            ]
        )
        repository.upsert_many(
            [
                NewsItem(
                    id="rss-keep",
                    title_cn="标题",
                    title_original="Title",
                    summary="摘要",
                    why_it_matters="",
                    source="OpenAI",
                    source_type="official",
                    published_at="2026-09-13T06:00:00+00:00",
                    category=NewsCategory.highlight,
                    tags=["OpenAI"],
                    url="https://openai.com/index/keep",
                    content_original="",
                )
            ]
        )
        session.commit()
        stored = repository.get_detail("rss-keep")
    finally:
        session.close()

    assert stored is not None
    assert stored.content_original == OPENAI_BODY
    assert stored.content_language == "en"
