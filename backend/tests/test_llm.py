
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.collectors.raw import RawArticle
from app.pipelines.urls import canonicalize_url
from app.services.llm.cache import LLMCache
from app.services.llm.client import LLMClient, LLMCompletion, LLMError, parse_completion_json
from app.services.llm.enrich import enrich_articles, sort_news_items
from app.services.llm.prompts import PROMPT_VERSION
from app.services.llm.schemas import ArticleEnrichment
from app.services.llm.settings import LLMSettings
from app.models import NewsItem, NewsCategory
from app.pipelines.normalize import news_item_from_raw


def make_raw(**kwargs) -> RawArticle:
    url = kwargs.get("url", "https://openai.com/index/example")
    defaults = dict(
        source_id="openai",
        source="OpenAI",
        source_type="official",
        title="Paul Christiano joins OpenAI Foundation Board",
        url=url,
        canonical_url=canonicalize_url(url),
        published_at=datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc),
        summary="Paul Christiano joins the OpenAI Foundation Board.",
    )
    defaults.update(kwargs)
    defaults["canonical_url"] = canonicalize_url(defaults["url"])
    return RawArticle(**defaults)


def enabled_settings(tmp_path: Path, **kwargs) -> LLMSettings:
    values = dict(
        enabled=True,
        api_key="test-key",
        model="test-model",
        base_url="https://example.invalid/v1",
        timeout=20.0,
        cache_dir=tmp_path / "llm-cache",
    )
    values.update(kwargs)
    return LLMSettings(**values)


def enrichment_json(**kwargs) -> str:
    payload = {
        "title_cn": "Paul Christiano 加入 OpenAI Foundation 董事会",
        "summary_cn": "OpenAI 宣布 Paul Christiano 加入基金会董事会，并参与安全相关委员会工作。",
        "why_it_matters": "这位对齐研究者进入董事会，会影响 OpenAI 的安全治理安排。",
        "importance_score": 88,
    }
    payload.update(kwargs)
    import json
    return json.dumps(payload, ensure_ascii=False)


class FakeClient:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0
        self.messages: list[list[dict[str, str]]] = []

    def complete(self, messages: list[dict[str, str]]) -> LLMCompletion:
        self.calls += 1
        self.messages.append(messages)
        if not self.outcomes:
            raise LLMError("no more outcomes")
        item = self.outcomes.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, LLMCompletion):
            return item
        return LLMCompletion(text=str(item), input_tokens=10, output_tokens=20)


def test_enrichment_writes_chinese_fields(tmp_path: Path) -> None:
    client = FakeClient([enrichment_json()])
    items, stats = enrich_articles(
        [make_raw()],
        settings=enabled_settings(tmp_path),
        cache=LLMCache(tmp_path / "llm-cache"),
        client=client,
    )
    assert stats.success == 1
    assert stats.llm_calls == 1
    item = items[0]
    assert item.title_cn == "Paul Christiano 加入 OpenAI Foundation 董事会"
    assert "OpenAI" in item.summary
    assert item.why_it_matters
    assert item.importance_score == 88
    assert item.title_original.startswith("Paul Christiano")


def test_importance_score_bounds() -> None:
    ArticleEnrichment.model_validate(
        {"title_cn": "标题", "summary_cn": "摘要", "why_it_matters": "", "importance_score": 0}
    )
    ArticleEnrichment.model_validate(
        {"title_cn": "标题", "summary_cn": "摘要", "why_it_matters": "", "importance_score": 100}
    )
    with pytest.raises(ValidationError):
        ArticleEnrichment.model_validate(
            {"title_cn": "标题", "summary_cn": "摘要", "why_it_matters": "", "importance_score": 101}
        )
    with pytest.raises(ValidationError):
        ArticleEnrichment.model_validate(
            {"title_cn": "标题", "summary_cn": "摘要", "why_it_matters": "", "importance_score": -1}
        )


def test_out_of_range_score_falls_back(tmp_path: Path) -> None:
    client = FakeClient([enrichment_json(importance_score=150), enrichment_json(importance_score=150)])
    items, stats = enrich_articles(
        [make_raw()],
        settings=enabled_settings(tmp_path),
        cache=LLMCache(tmp_path / "llm-cache"),
        client=client,
    )
    assert stats.failed == 1
    assert stats.fallback == 1
    assert items[0].title_cn == items[0].title_original
    assert items[0].importance_score is None


def test_malformed_json_falls_back(tmp_path: Path) -> None:
    client = FakeClient(["not-json", "still-not-json"])
    items, stats = enrich_articles(
        [make_raw()],
        settings=enabled_settings(tmp_path),
        cache=LLMCache(tmp_path / "llm-cache"),
        client=client,
    )
    assert stats.llm_calls == 2
    assert stats.fallback == 1
    assert items[0].importance_score is None


def test_timeout_retries_then_succeeds(tmp_path: Path) -> None:
    client = FakeClient([LLMError("LLM request timed out"), enrichment_json()])
    items, stats = enrich_articles(
        [make_raw()],
        settings=enabled_settings(tmp_path),
        cache=LLMCache(tmp_path / "llm-cache"),
        client=client,
    )
    assert client.calls == 2
    assert stats.llm_calls == 2
    assert stats.success == 1
    assert items[0].importance_score == 88


def test_timeout_then_fallback(tmp_path: Path) -> None:
    client = FakeClient([LLMError("LLM request timed out"), LLMError("LLM request timed out")])
    items, stats = enrich_articles(
        [make_raw()],
        settings=enabled_settings(tmp_path),
        cache=LLMCache(tmp_path / "llm-cache"),
        client=client,
    )
    assert stats.llm_calls == 2
    assert stats.failed == 1
    assert stats.fallback == 1
    assert items[0].title_cn == items[0].title_original


def test_one_failure_does_not_block_others(tmp_path: Path) -> None:
    client = FakeClient(
        [
            enrichment_json(title_cn="成功一条", importance_score=90),
            LLMError("LLM HTTP error"),
            LLMError("LLM HTTP error"),
            enrichment_json(title_cn="成功三条", importance_score=70),
        ]
    )
    articles = [
        make_raw(url="https://openai.com/a", title="A"),
        make_raw(url="https://openai.com/b", title="B", summary=""),
        make_raw(url="https://openai.com/c", title="C"),
    ]
    items, stats = enrich_articles(
        articles,
        settings=enabled_settings(tmp_path),
        cache=LLMCache(tmp_path / "llm-cache"),
        client=client,
    )
    by_url = {item.url: item for item in items}
    assert by_url["https://openai.com/a"].title_cn == "成功一条"
    assert by_url["https://openai.com/b"].title_cn == "B"
    assert by_url["https://openai.com/c"].title_cn == "成功三条"
    assert stats.success == 2
    assert stats.failed == 1
    assert stats.fallback == 1


def test_disabled_uses_original_content(tmp_path: Path) -> None:
    client = FakeClient([enrichment_json()])
    settings = enabled_settings(tmp_path, enabled=False, api_key="")
    items, stats = enrich_articles(
        [make_raw()],
        settings=settings,
        cache=LLMCache(tmp_path / "llm-cache"),
        client=client,
    )
    assert client.calls == 0
    assert stats.fallback == 1
    assert items[0].title_cn == items[0].title_original
    assert items[0].importance_score is None


def test_missing_api_key_skips_llm(tmp_path: Path) -> None:
    client = FakeClient([enrichment_json()])
    settings = enabled_settings(tmp_path, api_key="")
    items, stats = enrich_articles(
        [make_raw()],
        settings=settings,
        cache=LLMCache(tmp_path / "llm-cache"),
        client=client,
    )
    assert client.calls == 0
    assert stats.available is False
    assert items[0].why_it_matters == ""


def test_cache_hit_does_not_call_llm(tmp_path: Path) -> None:
    cache = LLMCache(tmp_path / "llm-cache")
    settings = enabled_settings(tmp_path)
    first_client = FakeClient([enrichment_json()])
    enrich_articles([make_raw()], settings=settings, cache=cache, client=first_client)
    second_client = FakeClient([enrichment_json(title_cn="不应使用")])
    items, stats = enrich_articles([make_raw()], settings=settings, cache=cache, client=second_client)
    assert second_client.calls == 0
    assert stats.cache_hits == 1
    assert stats.llm_calls == 0
    assert items[0].title_cn == "Paul Christiano 加入 OpenAI Foundation 董事会"


def test_content_change_cache_miss(tmp_path: Path) -> None:
    cache = LLMCache(tmp_path / "llm-cache")
    settings = enabled_settings(tmp_path)
    enrich_articles([make_raw()], settings=settings, cache=cache, client=FakeClient([enrichment_json()]))
    client = FakeClient([enrichment_json(title_cn="摘要已变化")])
    items, stats = enrich_articles(
        [make_raw(summary="A completely different summary")],
        settings=settings,
        cache=cache,
        client=client,
    )
    assert stats.cache_hits == 0
    assert client.calls == 1
    assert items[0].title_cn == "摘要已变化"


def test_prompt_version_change_cache_miss(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache = LLMCache(tmp_path / "llm-cache")
    settings = enabled_settings(tmp_path)
    enrich_articles([make_raw()], settings=settings, cache=cache, client=FakeClient([enrichment_json()]))
    monkeypatch.setattr("app.services.llm.enrich.PROMPT_VERSION", PROMPT_VERSION + "-test")
    client = FakeClient([enrichment_json(title_cn="新版本")])
    items, stats = enrich_articles([make_raw()], settings=settings, cache=cache, client=client)
    assert stats.cache_hits == 0
    assert items[0].title_cn == "新版本"


def test_model_change_cache_miss(tmp_path: Path) -> None:
    cache = LLMCache(tmp_path / "llm-cache")
    enrich_articles(
        [make_raw()],
        settings=enabled_settings(tmp_path, model="model-a"),
        cache=cache,
        client=FakeClient([enrichment_json()]),
    )
    client = FakeClient([enrichment_json(title_cn="新模型")])
    items, stats = enrich_articles(
        [make_raw()],
        settings=enabled_settings(tmp_path, model="model-b"),
        cache=cache,
        client=client,
    )
    assert stats.cache_hits == 0
    assert items[0].title_cn == "新模型"


def test_sorts_by_importance_then_published_at() -> None:
    def item(score, published, title):
        return NewsItem(
            id=title,
            title_cn=title,
            title_original=title,
            summary="",
            why_it_matters="",
            source="OpenAI",
            source_type="official",
            published_at=published,
            category=NewsCategory.highlight,
            tags=[],
            url=f"https://example.com/{title}",
            importance_score=score,
        )

    items = sort_news_items(
        [
            item(70, "2026-09-10T12:00:00+00:00", "mid-old"),
            item(None, "2026-09-10T18:00:00+00:00", "none-new"),
            item(90, "2026-09-10T10:00:00+00:00", "high-old"),
            item(90, "2026-09-10T16:00:00+00:00", "high-new"),
            item(None, "2026-09-10T08:00:00+00:00", "none-old"),
        ]
    )
    assert [entry.title_cn for entry in items] == ["high-new", "high-old", "mid-old", "none-new", "none-old"]


def test_parse_completion_json_rejects_malformed() -> None:
    with pytest.raises(LLMError):
        parse_completion_json("not json")


def test_http_timeout_becomes_llm_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def boom(*args, **kwargs):
        raise httpx.TimeoutException("slow")

    monkeypatch.setattr(httpx.Client, "post", boom)
    client = LLMClient(enabled_settings(tmp_path))
    with pytest.raises(LLMError, match="timed out"):
        client.complete([{"role": "user", "content": "hi"}])
