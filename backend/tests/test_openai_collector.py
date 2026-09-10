from datetime import datetime, timezone

import httpx
from app.collectors.openai import collect_openai_news, parse_openai_feed, within_last_hours
from app.pipelines.normalize import news_item_from_raw, stable_news_id
from app.services.digest_store import DigestStore

FROZEN_NOW = datetime(2026, 9, 10, 20, 0, tzinfo=timezone.utc)


def test_parse_multiple_articles(openai_rss_xml: str) -> None:
    result = parse_openai_feed(openai_rss_xml)
    assert result.fetched == 7
    assert len(result.valid) == 4
    assert result.skipped == 3
    titles = {item.title for item in result.valid}
    assert "GPT-6 Astra: The next generation in intelligence for work" in titles
    assert "The AI policy window is open. We need to act." in titles


def test_missing_summary_is_valid(openai_rss_xml: str) -> None:
    result = parse_openai_feed(openai_rss_xml)
    item = next(article for article in result.valid if "without a summary" in article.title)
    assert item.summary == ""
    news = news_item_from_raw(item)
    assert news.summary == ""
    assert news.why_it_matters == ""
    assert news.title_cn == news.title_original == item.title


def test_invalid_date_is_skipped(openai_rss_xml: str) -> None:
    result = parse_openai_feed(openai_rss_xml)
    urls = {item.url for item in result.valid}
    assert "https://openai.com/index/broken-date" not in urls


def test_stable_id() -> None:
    url = "https://openai.com/index/gpt-6-astra"
    first = stable_news_id(url)
    second = stable_news_id(url)
    assert first == second
    assert first.startswith("openai-")
    assert stable_news_id(url + "/") != first


def test_last_24h_filter(openai_rss_xml: str) -> None:
    result = parse_openai_feed(openai_rss_xml)
    recent = [item for item in result.news_items if within_last_hours(item, FROZEN_NOW)]
    urls = {item.url for item in recent}
    assert "https://openai.com/index/gpt-6-astra" in urls
    assert "https://openai.com/index/ai-policy-window" in urls
    assert "https://openai.com/index/codex-update" in urls
    assert "https://openai.com/index/old-research-recap" not in urls
    assert len(recent) == 3


def test_empty_feed_returns_no_news() -> None:
    result = parse_openai_feed("<rss version='2.0'><channel><title>Empty</title></channel></rss>")
    assert result.fetched == 0
    assert result.valid == []
    assert result.news_items == []


def test_unparseable_rss_does_not_crash() -> None:
    result = parse_openai_feed("this is not xml {{{")
    assert result.fetched == 0
    assert result.valid == []


def test_network_failure_does_not_crash() -> None:
    def boom(url: str, timeout: float = 10.0) -> str:
        raise httpx.ConnectError("offline")

    result = collect_openai_news(fetch_text=boom)
    assert result.fetched == 0
    assert result.valid == []
    assert result.error
    assert result.news_items == []


def test_store_refresh_builds_today_digest(openai_rss_xml: str) -> None:
    store = DigestStore()
    store.refresh(now=FROZEN_NOW, fetch_text=lambda url, timeout=10.0: openai_rss_xml)
    digest = store.get_today()
    assert digest.date == "2026-09-10"
    assert len(digest.news) == 3
    assert store.get_by_date("2026-09-09") is None
    news = store.get_news(digest.news[0].id)
    assert news is not None
    assert news.source == "OpenAI"
    assert news.source_type == "official"


def test_store_empty_when_all_old() -> None:
    xml = """<?xml version='1.0'?><rss version='2.0'><channel>
    <item>
      <title>Ancient post</title>
      <link>https://openai.com/index/ancient</link>
      <pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate>
    </item>
    </channel></rss>"""
    store = DigestStore()
    store.refresh(now=FROZEN_NOW, fetch_text=lambda url, timeout=10.0: xml)
    digest = store.get_today()
    assert digest.news == []
    assert digest.date == "2026-09-10"
