"""Phase 10.3: the expanded source set, exercised entirely from local fixtures.

Each collector is checked against a captured page or feed so the suite never
depends on the network, plus the cross-cutting behaviour the phase promises:
per-source failure isolation, URL canonicalization, and official-over-media
dedupe.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.collectors.html import (
    PageStructureError,
    anthropic_entries,
    collect_html_source,
    cohere_entries,
    cursor_entries,
    deepseek_entries,
    deepseek_links,
    kimi_entries,
    parse_html_page,
)
from app.collectors.raw import RawArticle
from app.collectors.rss import collect_all_sources, parse_feed
from app.config.sources import (
    NEWS_SOURCE_KINDS,
    NEWS_SOURCE_TYPES,
    enabled_sources,
    source_by_id,
)
from app.pipelines.dedup import dedupe_articles
from app.pipelines.urls import canonicalize_url
from app.services.digest_store import DigestStore
from tests.conftest import EMPTY_RSS, make_fixture_fetch, read_fixture

UTC = timezone.utc
ANTHROPIC_XML = read_fixture("anthropic_news.html")
DEEPSEEK_INDEX = read_fixture("deepseek_index.html")
DEEPSEEK_NEWS = read_fixture("deepseek_news.html")
KIMI_BLOG = read_fixture("kimi_blog.html")
COHERE_BLOG = read_fixture("cohere_blog.html")
CURSOR_BLOG = read_fixture("cursor_blog.html")


# --- source configuration ---


def test_every_source_declares_a_supported_kind() -> None:
    for source in enabled_sources():
        assert source.kind in NEWS_SOURCE_KINDS, source.id
        assert source.url.startswith("https://"), source.id
        assert source.source_type in NEWS_SOURCE_TYPES, source.id


def test_new_sources_are_enabled_with_expected_types() -> None:
    expected = {
        "anthropic": "official",
        "meta": "official",
        "nvidia": "official",
        "deepseek": "official",
        "qwen": "official",
        "kimi": "official",
        "techcrunch-ai": "media",
        "mistral": "official",
        "cohere": "official",
        "cursor": "official",
        "microsoft-research": "research",
        "ars-technica": "media",
    }
    found = {source.id: source.source_type for source in enabled_sources()}
    for source_id, source_type in expected.items():
        assert found[source_id] == source_type


def test_official_outranks_research_outranks_media() -> None:
    """Priority numbers are banded by source class, so dedupe can trust them."""
    priorities = {source.id: source.priority for source in enabled_sources()}
    official = [priorities[s.id] for s in enabled_sources() if s.source_type == "official"]
    research = [priorities[s.id] for s in enabled_sources() if s.source_type == "research"]
    media = [priorities[s.id] for s in enabled_sources() if s.source_type == "media"]
    assert max(official) < min(research)
    assert max(research) < min(media)


def test_source_types_are_exactly_the_three_documented_classes() -> None:
    """Phase 10.11 replaced the old ``blog`` class with ``research``.

    The list matters because the client renders whatever the backend sends: a
    fourth value would reach the UI as an untranslated string, and ``blog``
    would quietly put Hugging Face back in its own bucket.
    """
    assert set(NEWS_SOURCE_TYPES) == {"official", "research", "media"}
    assert "blog" not in NEWS_SOURCE_TYPES
    assert all(source.source_type != "blog" for source in enabled_sources())


def test_hugging_face_is_a_research_source() -> None:
    """Hugging Face publishes research, not reporting, so it is not media."""
    assert source_by_id("huggingface").source_type == "research"


def test_every_enabled_source_has_a_unique_id_and_a_kind() -> None:
    sources = enabled_sources()
    assert len({source.id for source in sources}) == len(sources)
    assert all(source.kind in NEWS_SOURCE_KINDS for source in sources)


def test_github_trending_is_not_a_news_source() -> None:
    """GitHub stays a developer signal with its own collector and its own page.

    Folding it into ``SOURCES`` would give it a source_type, a priority and a
    place in dedupe and ranking, none of which apply to a repository listing.
    """
    from app.config.sources import all_sources

    assert all(not source.id.startswith("github") for source in all_sources())
    assert all("github.com/trending" not in source.url for source in all_sources())


# --- RSS sources ---


def test_nvidia_feed_parses(nvidia_rss_xml: str) -> None:
    result = parse_feed(nvidia_rss_xml, source_by_id("nvidia"))
    assert result.fetched == 2
    assert len(result.valid) == 2
    assert result.valid[0].published_at == datetime(2026, 9, 10, 16, 30, 35, tzinfo=UTC)
    assert result.valid[0].source == "NVIDIA"


def test_qwen_feed_keeps_the_offset(qwen_rss_xml: str) -> None:
    """A +0800 pubDate is stored as the equivalent UTC instant."""
    result = parse_feed(qwen_rss_xml, source_by_id("qwen"))
    assert len(result.valid) == 2
    assert result.valid[0].published_at == datetime(2025, 9, 22, 20, 0, tzinfo=UTC)
    assert result.valid[0].published_at.astimezone(timezone.utc).hour == 20


def test_techcrunch_feed_parses(techcrunch_rss_xml: str) -> None:
    result = parse_feed(techcrunch_rss_xml, source_by_id("techcrunch-ai"))
    assert len(result.valid) == 2
    assert result.valid[0].source_type == "media"


def test_quantum_bit_ai_is_no_longer_collected() -> None:
    """Phase 10.11 dropped 量子位: its feed must not be reachable any more."""
    source_ids = {source.id for source in enabled_sources()}
    assert "qbitai" not in source_ids
    assert all("qbitai" not in source.url for source in enabled_sources())


def test_mistral_feed_parses(mistral_rss_xml: str) -> None:
    """Mistral publishes a real RSS feed, so it needs no HTML collector."""
    source = source_by_id("mistral")
    assert source.kind == "rss"
    result = parse_feed(mistral_rss_xml, source)
    assert result.success is True
    assert len(result.valid) == 2
    first = result.valid[0]
    assert first.title.startswith("Cloudera and Mistral Partner")
    assert first.url == "https://mistral.ai/news/mistral-x-cloudera/"
    assert first.published_at == datetime(2026, 9, 10, 10, 42, 55, tzinfo=UTC)
    assert first.summary.startswith("Cloudera and Mistral join forces")
    assert first.source == "Mistral AI"
    assert first.source_type == "official"


def test_microsoft_research_feed_parses(microsoft_research_rss_xml: str) -> None:
    source = source_by_id("microsoft-research")
    assert source.kind == "rss"
    result = parse_feed(microsoft_research_rss_xml, source)
    assert result.success is True
    assert len(result.valid) == 2
    first = result.valid[0]
    assert first.title.startswith("GigaPath-Flash and GigaTIME-Flash")
    assert first.url.startswith("https://www.microsoft.com/en-us/research/blog/")
    assert first.published_at == datetime(2026, 8, 31, 16, 0, tzinfo=UTC)
    assert first.summary
    # The feed declares its own offset (+0000); the stored instant stays UTC.
    assert first.published_at.tzinfo is not None
    assert first.source == "Microsoft Research"
    assert first.source_type == "research"


def test_ars_technica_feed_drops_the_non_ai_half(ars_technica_rss_xml: str) -> None:
    """The AI category still carries stories that are not about AI.

    The robot-dog review is a gadgets piece that happens to mention robotics;
    the Claude story is real AI news. The filter has to tell them apart before
    either reaches dedupe, ranking or the LLM.
    """
    source = source_by_id("ars-technica")
    assert source.requires_ai_filter is True
    result = parse_feed(ars_technica_rss_xml, source)

    assert result.success is True
    titles = [article.title for article in result.valid]
    assert "Claude users found ways around safeguards for bioweapons research" in titles
    assert "I spent $4,000 on a robot dog from China" not in titles
    # The dropped entry is counted, not silently lost.
    assert result.fetched == 2
    assert result.skipped == 1


def test_ars_technica_keeps_metadata_of_the_kept_story(ars_technica_rss_xml: str) -> None:
    source = source_by_id("ars-technica")
    result = parse_feed(ars_technica_rss_xml, source)
    article = result.valid[0]
    assert article.url.startswith("https://arstechnica.com/ai/2026/09/")
    assert article.published_at == datetime(2026, 9, 11, 13, 2, 35, tzinfo=UTC)
    assert article.summary.startswith("Some dangerous biology")
    assert article.source == "Ars Technica"
    assert article.source_type == "media"


# --- HTML sources ---


def test_anthropic_page_parses() -> None:
    entries = anthropic_entries(ANTHROPIC_XML)
    urls = [url for url, _title, _published in entries]
    assert "https://www.anthropic.com/news/claude-opus-5" in urls
    titled = {url: title for url, title, _ in entries}
    assert titled["https://www.anthropic.com/news/claude-opus-5"] == "Introducing Claude Opus 5"
    # The featured card carries the title in an <h4>, the list card in a span.
    assert titled["https://www.anthropic.com/news/wellbeing-research-grants"].startswith("Funding")
    # The undated card is skipped rather than guessed at.
    assert "https://www.anthropic.com/news/untimed-note" not in urls


def test_anthropic_page_without_cards_is_a_structure_error() -> None:
    with pytest.raises(PageStructureError):
        anthropic_entries("<html><body><p>Nothing here</p></body></html>")


def test_kimi_payload_parses_both_relative_and_absolute_links() -> None:
    entries = kimi_entries(KIMI_BLOG)
    by_url = {url: (title, published) for url, title, published in entries}
    assert len(entries) == 3
    relative = by_url["https://www.kimi.com/en/blog/kimi-k2-6"]
    assert relative[0] == "Kimi K2.6"
    assert relative[1] == datetime(2026, 4, 20, tzinfo=UTC)
    # A link that is already absolute must not be prefixed again.
    assert "https://github.com/MoonshotAI/Moonlight" in by_url


def test_kimi_payload_without_article_list_is_a_structure_error() -> None:
    with pytest.raises(PageStructureError):
        kimi_entries("<html><body><script>self.__next_f.push([1,\"[]\"])</script></body></html>")


def test_deepseek_index_lists_the_newest_release_page() -> None:
    assert deepseek_links(DEEPSEEK_INDEX) == ["/news/news260910"]


def test_cohere_page_parses_its_dated_cards() -> None:
    """Every card prints its publish date in an eyebrow line above the link."""
    entries = cohere_entries(COHERE_BLOG)
    by_url = {url: (title, published) for url, title, published in entries}

    assert len(entries) == 3
    assert by_url["https://cohere.com/blog/north-small-translate"] == (
        "Introducing North Small Translate: A leading sovereign open-weight machine translation model",
        datetime(2026, 9, 10, tzinfo=UTC),
    )
    assert by_url["https://cohere.com/blog/who-gets-to-define-the-rules-for-ai"][0] == (
        "Who Gets to Define the Rules for AI?"
    )
    # The card without an eyebrow date is skipped rather than guessed at, and a
    # /blog/tag/ chip is not an article.
    assert "https://cohere.com/blog/undated-teaser" not in by_url
    assert all("/tag/" not in url for url in by_url)


def test_cohere_page_without_blog_links_is_a_structure_error() -> None:
    with pytest.raises(PageStructureError):
        cohere_entries("<html><body><p>Redesigned</p></body></html>")


def test_cursor_page_parses_its_dated_rows() -> None:
    entries = cursor_entries(CURSOR_BLOG)
    by_url = {url: (title, published) for url, title, published in entries}

    assert len(entries) == 2
    # The headline is the row's own <p>, not the author name or the reading time.
    assert by_url["https://cursor.com/blog/projects"] == (
        "Introducing Projects",
        datetime(2026, 9, 10, 12, 0, tzinfo=UTC),
    )
    assert by_url["https://cursor.com/blog/self-hosted-machines"][0] == (
        "Run cloud agents on machines you manage"
    )
    # A row whose date column is missing, and a featured card without a <time>,
    # are both skipped.
    assert "https://cursor.com/blog/undated-row" not in by_url
    assert "https://cursor.com/blog/undated-feature" not in by_url


def test_cursor_page_without_blog_links_is_a_structure_error() -> None:
    with pytest.raises(PageStructureError):
        cursor_entries("<html><body><p>Redesigned</p></body></html>")


def test_cohere_and_cursor_listing_collectors_agree_with_configuration(
    cohere_blog_html: str, cursor_blog_html: str
) -> None:
    """End to end through the HTML collector, not just the entry parser."""
    cases = [
        ("cohere", cohere_blog_html, "Cohere", "official"),
        ("cursor", cursor_blog_html, "Cursor", "official"),
    ]
    for source_id, html, name, source_type in cases:
        result = collect_html_source(
            source_by_id(source_id),
            fetch_text=lambda url, timeout=10.0, _html=html: _html,
        )
        assert result.success is True, result.error
        assert result.valid, source_id
        assert all(article.source == name for article in result.valid)
        assert all(article.source_type == source_type for article in result.valid)
        assert all(article.published_at is not None for article in result.valid)


def test_deepseek_listing_parses_title_and_date() -> None:
    entries = deepseek_entries(DEEPSEEK_NEWS)
    by_url = {url: (title, published) for url, title, published in entries}
    assert len(entries) == 3
    assert by_url["https://api-docs.deepseek.com/news/news260910"][0] == (
        "DeepSeek-V4.1-Flash Release"
    )
    assert by_url["https://api-docs.deepseek.com/news/news260910"][1] == datetime(
        2026, 9, 10, tzinfo=UTC
    )
    # The sidebar's own "News" heading has no date and is dropped.
    assert all(title for title, _ in by_url.values())


def test_html_page_without_entries_succeeds_with_nothing() -> None:
    """An empty listing behaves like an empty feed, not like a failure."""
    empty = "<html><body><a href=\"/news/placeholder\">Undated</a></body></html>"
    result = parse_html_page(source_by_id("anthropic"), index_html=empty)
    assert result.success is True
    assert result.valid == []
    assert result.fetched == 0


def test_html_source_reports_an_unreachable_page_without_raising() -> None:
    def boom(url: str, timeout: float = 10.0) -> str:
        raise httpx.ConnectError("offline")

    result = collect_html_source(source_by_id("anthropic"), fetch_text=boom)
    assert result.success is False
    assert result.error
    assert result.valid == []


def test_html_source_reports_changed_markup_without_raising() -> None:
    result = collect_html_source(
        source_by_id("kimi"),
        fetch_text=lambda url, timeout=10.0: "<html><body>redesigned</body></html>",
    )
    assert result.success is False
    assert "article list" in (result.error or "")


def test_html_source_rejects_an_empty_response() -> None:
    result = collect_html_source(source_by_id("anthropic"), fetch_text=lambda url, timeout=10.0: "")
    assert result.success is False
    assert result.error == "Empty HTML response"


def test_deepseek_index_failure_does_not_fetch_the_listing() -> None:
    calls: list[str] = []

    def fetch(url: str, timeout: float = 10.0) -> str:
        calls.append(url)
        return "<html><body><p>moved</p></body></html>"

    result = collect_html_source(source_by_id("deepseek"), fetch_text=fetch)
    assert result.success is False
    assert len(calls) == 1


def test_deepseek_uses_the_pages_fixture_end_to_end(deepseek_index_html: str, deepseek_news_html: str) -> None:
    """The index is followed to the newest release page, then parsed."""
    fetch = make_fixture_fetch(
        read_fixture("openai_news.xml"),
        read_fixture("deepmind_blog.xml"),
        read_fixture("huggingface_blog.xml"),
        pages={
            source_by_id("deepseek").url: deepseek_index_html,
            "https://api-docs.deepseek.com/news/news260910": deepseek_news_html,
        },
    )
    result = collect_html_source(source_by_id("deepseek"), fetch_text=fetch)
    assert result.success is True
    assert len(result.valid) == 3
    assert result.valid[0].source_id == "deepseek"


# --- cross-source behaviour ---


def test_one_html_source_failing_does_not_drop_the_others(
    openai_rss_xml: str,
    deepmind_rss_xml: str,
    huggingface_rss_xml: str,
    anthropic_news_html: str,
) -> None:
    fetch = make_fixture_fetch(
        openai_rss_xml,
        deepmind_rss_xml,
        huggingface_rss_xml,
        failing={"kimi"},
        pages={source_by_id("anthropic").url: anthropic_news_html},
    )
    reports = {report.source_id: report for report in collect_all_sources(fetch_text=fetch)}

    assert reports["anthropic"].success is True
    assert len(reports["anthropic"].valid) == 3
    assert reports["openai"].success is True
    assert reports["kimi"].success is False
    assert reports["kimi"].error
    # Only the failing source is reported as failed.
    assert [report.source_name for report in reports.values() if report.error] == ["Kimi"]


def test_every_enabled_source_is_attempted_even_when_others_fail(
    openai_rss_xml: str, deepmind_rss_xml: str, huggingface_rss_xml: str
) -> None:
    everything_fails = {source.id for source in enabled_sources()}
    fetch = make_fixture_fetch(
        openai_rss_xml, deepmind_rss_xml, huggingface_rss_xml, failing=everything_fails
    )
    reports = collect_all_sources(fetch_text=fetch)
    assert len(reports) == len(enabled_sources())
    assert all(report.success is False for report in reports)
    assert all(report.error for report in reports)


def test_unknown_urls_still_fail_the_source(openai_rss_xml: str) -> None:
    """A source whose URL has no fixture must fail, never silently pass."""
    fetch = make_fixture_fetch(openai_rss_xml, EMPTY_RSS, EMPTY_RSS, failing={"nvidia"})
    reports = {report.source_id: report for report in collect_all_sources(fetch_text=fetch)}
    assert reports["nvidia"].success is False


def test_new_source_urls_are_canonicalized_for_dedupe() -> None:
    tracked = "https://blogs.nvidia.com/blog/skild-ai-s1-physical-ai/?utm_source=rss&utm_medium=feed"
    assert canonicalize_url(tracked) == "https://blogs.nvidia.com/blog/skild-ai-s1-physical-ai"
    # The same story reached through two shapes of URL collapses to one id.
    assert canonicalize_url(tracked) == canonicalize_url(
        "https://blogs.nvidia.com/blog/skild-ai-s1-physical-ai/"
    )


def test_official_source_wins_over_media_for_the_same_story() -> None:
    published = datetime(2026, 9, 12, 19, 34, 44, tzinfo=UTC)

    def article(source_id: str) -> RawArticle:
        source = source_by_id(source_id)
        url = f"https://example.com/{source_id}/anthropic-pace"
        return RawArticle(
            source_id=source.id,
            source=source.name,
            source_type=source.source_type,
            title="Anthropic CEO outlines plan to pace the frontier",
            url=url,
            canonical_url=canonicalize_url(url),
            published_at=published,
            summary="",
        )

    media = article("techcrunch-ai")
    official = article("anthropic")
    winners = dedupe_articles([media, official])
    assert len(winners) == 1
    assert winners[0].source_id == "anthropic"
    # Order of collection must not change the outcome.
    assert dedupe_articles([official, media])[0].source_id == "anthropic"


def test_cross_source_dedupe_collapses_a_shared_story(
    openai_rss_xml: str, deepmind_rss_xml: str, huggingface_rss_xml: str
) -> None:
    """OpenAI and DeepMind reporting one story still yields one digest entry."""
    fetch = make_fixture_fetch(openai_rss_xml, deepmind_rss_xml, huggingface_rss_xml)
    reports = collect_all_sources(fetch_text=fetch)
    merged = [article for report in reports for article in report.valid]
    deduped = dedupe_articles(merged)
    titles = [article.title for article in deduped]
    assert titles.count("GPT-6 Astra: The next generation in intelligence for work") == 1


def test_digest_links_every_enabled_source_that_has_news(
    openai_rss_xml: str,
    deepmind_rss_xml: str,
    huggingface_rss_xml: str,
    anthropic_news_html: str,
    kimi_blog_html: str,
) -> None:
    """A digest links the new sources alongside the old ones.

    The fixture pages carry older publish dates than the 24h first-run window,
    so this drives an explicit wide window: membership is the window, not the
    source, and the point here is that all four sources end up linked.
    """
    from tests.conftest import FROZEN_NOW
    from app.services.digest_window import DigestWindow

    fetch = make_fixture_fetch(
        openai_rss_xml,
        deepmind_rss_xml,
        huggingface_rss_xml,
        pages={
            source_by_id("anthropic").url: anthropic_news_html,
            source_by_id("kimi").url: kimi_blog_html,
        },
    )
    window = DigestWindow(
        start=datetime(2025, 1, 1, tzinfo=UTC),
        end=FROZEN_NOW,
    )
    store = DigestStore()
    news_items, _reports = store.collect_news(window, FROZEN_NOW, fetch)
    store.persist(date="2026-09-11", window=window, news_items=news_items, github_projects=[])
    sources = {item.source for item in store.get_today().news}
    assert {"OpenAI", "Google DeepMind", "Hugging Face", "Anthropic"} <= sources
