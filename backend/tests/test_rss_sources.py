from datetime import datetime, timezone

import httpx
from app.collectors.rss import collect_all_sources, parse_feed
from app.config.sources import source_by_id
from app.services.digest_store import DigestStore
from tests.conftest import FROZEN_DIGEST_DATE, make_fixture_fetch

FROZEN_NOW = datetime(2026, 9, 10, 20, 0, tzinfo=timezone.utc)


def test_three_sources_parse(openai_rss_xml: str, deepmind_rss_xml: str, huggingface_rss_xml: str) -> None:
    openai = parse_feed(openai_rss_xml, source_by_id("openai"))
    deepmind = parse_feed(deepmind_rss_xml, source_by_id("deepmind"))
    huggingface = parse_feed(huggingface_rss_xml, source_by_id("huggingface"))
    assert len(openai.valid) == 4
    assert len(deepmind.valid) == 3
    assert len(huggingface.valid) == 3


def test_deepmind_missing_summary(deepmind_rss_xml: str) -> None:
    result = parse_feed(deepmind_rss_xml, source_by_id("deepmind"))
    item = next(article for article in result.valid if article.title == "Scaling world models")
    assert item.summary == ""


def test_huggingface_guid_as_url(huggingface_rss_xml: str) -> None:
    result = parse_feed(huggingface_rss_xml, source_by_id("huggingface"))
    item = next(article for article in result.valid if article.title == "Cool Model Card")
    assert item.url == "https://huggingface.co/blog/cool-model"


def test_one_source_failure_does_not_drop_others(openai_rss_xml: str, deepmind_rss_xml: str, huggingface_rss_xml: str) -> None:
    fetch = make_fixture_fetch(openai_rss_xml, deepmind_rss_xml, huggingface_rss_xml, failing={"deepmind"})
    reports = collect_all_sources(fetch_text=fetch)
    by_id = {report.source_id: report for report in reports}
    assert by_id["openai"].success
    assert by_id["huggingface"].success
    assert not by_id["deepmind"].success
    assert by_id["deepmind"].error

    store = DigestStore()
    store.refresh(now=FROZEN_NOW, fetch_text=fetch)
    sources = {item.source for item in store.get_today().news}
    assert "OpenAI" in sources
    assert "Hugging Face" in sources
    assert "Google DeepMind" not in sources


def test_store_merges_and_dedupes(openai_rss_xml: str, deepmind_rss_xml: str, huggingface_rss_xml: str) -> None:
    fetch = make_fixture_fetch(openai_rss_xml, deepmind_rss_xml, huggingface_rss_xml)
    store = DigestStore()
    store.refresh(now=FROZEN_NOW, fetch_text=fetch)
    digest = store.get_today()
    titles = [item.title_original for item in digest.news]
    assert titles.count("GPT-6 Astra: The next generation in intelligence for work") == 1
    winner = next(item for item in digest.news if "GPT-6 Astra" in item.title_original)
    assert winner.source == "OpenAI"
    sources = {item.source for item in digest.news}
    assert sources == {"OpenAI", "Google DeepMind", "Hugging Face"}
    assert len(digest.news) == 6


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
    assert digest.date == FROZEN_DIGEST_DATE
