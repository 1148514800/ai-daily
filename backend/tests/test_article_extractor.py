"""Phase 10.5: original article bodies, grounded summaries, detail API.

The extractor's contract is that a body is never lost, never translated, and
never the reason a refresh fails. These tests pin each of those down, plus the
fallback ladder (feed body -> web page -> feed summary) in both directions:
what must be promoted and what must not.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.collectors.http import FetchError, FetchResult
from app.collectors.raw import RawArticle
from app.pipelines.urls import canonicalize_url
from app.services.article_extractor import (
    ArticleContentCache,
    ExtractionSettings,
    clean_html,
    detect_language,
    extract_article,
    extract_articles,
    format_extraction_stats,
    truncate_for_llm,
)

UTC = timezone.utc

SHORT_SUMMARY = "OpenAI 今天发布了新的推理模式。"


def settings(**kwargs) -> ExtractionSettings:
    values = dict(rss_full_min_chars=600, web_min_chars=200, max_chars=40000)
    values.update(kwargs)
    return ExtractionSettings(**values)


def page(body: str, *, content_type: str = "text/html; charset=utf-8", status: int = 200) -> FetchResult:
    return FetchResult(
        url="https://example.com/a",
        status=status,
        content_type=content_type,
        text=body,
    )


def article_page(*paragraphs: str) -> str:
    body = "\n".join(f"<p>{text}</p>" for text in paragraphs)
    return f"<html><body><article><h1>Title</h1>{body}</article></body></html>"


# Long enough to be mistaken for a whole article by the configured threshold,
# which is what separates "the feed carries the body" from "the feed carries a
# teaser". Anything shorter is deliberately a teaser in these tests.
LONG_ENGLISH = (
    "OpenAI introduced a new reasoning mode today that lets the model spend more "
    "time on a problem before answering. The company says the mode is available "
    "in the API immediately and that it improves results on multi-step tasks. "
    "It also published evaluation numbers comparing the new mode with the "
    "previous default, and said pricing is unchanged for the first month. "
    "Engineers on the team described the change as a shift in how the model "
    "allocates compute, rather than a new model release, and said the same "
    "weights are used throughout. Early users reported better results on long "
    "multi-step tool use, while simpler prompts became noticeably slower, so the "
    "mode is opt-in for now. A separate note said the older mode stays the "
    "default until the team has more data from production traffic."
)

LONG_CHINESE = (
    "OpenAI 今天发布了新的推理模式，模型在回答之前会花更多时间思考问题。"
    "官方表示该模式已经可以在 API 中直接使用，并且在多步任务上的效果明显更好。"
    "公司同时公布了与旧默认模式的评测对比结果，并表示首月价格保持不变。"
    "团队工程师称这次变化改变的是模型分配算力的方式，并不是发布新模型，"
    "整个过程中使用的仍然是同一套权重参数。"
    "早期用户反馈称在长链路工具调用上效果更好，但简单问题的响应速度明显变慢，"
    "因此该模式目前仍然需要手动开启。"
    "另有说明表示，在收集到更多线上流量数据之前，旧模式将继续作为默认选项。"
)


def make_raw(**kwargs) -> RawArticle:
    url = kwargs.pop("url", "https://example.com/a")
    values = dict(
        source_id="openai",
        source="OpenAI",
        source_type="official",
        title="A new reasoning mode",
        url=url,
        canonical_url=canonicalize_url(url),
        published_at=datetime(2026, 9, 13, 6, 0, tzinfo=UTC),
        summary=SHORT_SUMMARY,
    )
    values.update(kwargs)
    return RawArticle(**values)


# --- 1. the feed already carries the whole article ---


def test_rss_full_content_is_used_without_fetching_the_page() -> None:
    calls: list[str] = []

    def fetch(url: str, *, timeout: float = 10.0):
        calls.append(url)
        return page(article_page("should not be used"))

    content = extract_article(
        url="https://example.com/a",
        title="A new reasoning mode",
        feed_body=f"<p>{LONG_ENGLISH}</p>",
        feed_summary=SHORT_SUMMARY,
        settings=settings(),
        fetch=fetch,
    )

    assert content.method == "rss_full"
    assert LONG_ENGLISH in content.text
    assert content.language == "en"
    # The page is not fetched when the feed already has the article.
    assert calls == []


def test_short_feed_body_is_a_teaser_and_goes_to_the_page() -> None:
    content = extract_article(
        url="https://example.com/a",
        title="A new reasoning mode",
        feed_body="<p>Too short to be the article.</p>",
        feed_summary=SHORT_SUMMARY,
        settings=settings(),
        fetch=lambda url, timeout=10.0: page(article_page(LONG_ENGLISH)),
    )

    assert content.method == "web"
    assert LONG_ENGLISH in content.text


# --- 2. the page is the body when the feed only has a summary ---


def test_rss_summary_alone_promotes_to_the_web_body() -> None:
    content = extract_article(
        url="https://example.com/a",
        title="A new reasoning mode",
        feed_summary=SHORT_SUMMARY,
        settings=settings(),
        fetch=lambda url, timeout=10.0: page(article_page(LONG_ENGLISH)),
    )

    assert content.method == "web"
    assert LONG_ENGLISH in content.text


# --- 3. page chrome is filtered out ---


def test_navigation_footer_and_cookie_banner_are_filtered() -> None:
    html = f"""
    <html><body>
      <nav class="site-nav"><a href="/">Home</a><a href="/news">News</a></nav>
      <div class="cookie-consent">We use cookies. <button>Accept all</button></div>
      <header class="site-header"><a href="/subscribe">Subscribe</a></header>
      <article>
        <h1>Title</h1>
        <p>{LONG_ENGLISH}</p>
        <div class="share-buttons"><a href="/share">Share on X</a></div>
        <p>Second paragraph with the evaluation numbers and the pricing note.</p>
      </article>
      <aside class="related-posts"><h3>Related</h3><a href="/other">Another post</a></aside>
      <div class="newsletter-signup">Sign up for our newsletter</div>
      <footer class="site-footer"><p>Copyright 2026 Example Inc.</p></footer>
      <script>window.tracker = 1;</script>
      <style>.a{{color:red}}</style>
    </body></html>
    """

    text = clean_html(html, title="Title", settings=settings())

    assert LONG_ENGLISH in text
    assert "Second paragraph" in text
    for chrome in (
        "Home",
        "We use cookies",
        "Subscribe",
        "Share on X",
        "Related",
        "Another post",
        "newsletter",
        "Copyright 2026",
        "window.tracker",
        "color:red",
    ):
        assert chrome not in text


def test_headings_lists_and_quotes_keep_their_shape() -> None:
    html = """
    <article>
      <h2>Highlights</h2>
      <ul><li>First point</li><li>Second point</li></ul>
      <blockquote>The company said the mode is available today.</blockquote>
      <p>Closing paragraph with enough words to be kept as a real paragraph of text.</p>
    </article>
    """

    text = clean_html(html, settings=settings())

    assert "## Highlights" in text
    assert "- First point" in text
    assert "> The company said" in text
    assert "Closing paragraph" in text


def test_a_short_page_does_not_replace_the_feed_summary() -> None:
    """A paywall stub must not become the body."""
    content = extract_article(
        url="https://example.com/a",
        title="A new reasoning mode",
        feed_summary=SHORT_SUMMARY,
        settings=settings(),
        fetch=lambda url, timeout=10.0: page("<html><body><p>Log in to continue.</p></body></html>"),
    )

    assert content.method == "rss_summary"
    assert content.text == SHORT_SUMMARY


def test_a_boilerplate_looking_body_class_does_not_erase_the_article() -> None:
    """``navigation-with-keyboard`` is a real DeepSeek <body> class.

    Matching "nav" as a substring would decompose the whole document and lose
    the article, so a token must match as a whole word.
    """
    html = f'<html><body class="navigation-with-keyboard"><article><p>{LONG_ENGLISH}</p></article></body></html>'

    text = clean_html(html, settings=settings())

    assert LONG_ENGLISH in text


def test_the_largest_candidate_wins_over_a_related_post_card() -> None:
    """A page whose body is in <main> often also has a tiny <article> card."""
    related = '<article class="card"><a href="/other">A related headline</a></article>'
    html = f"""
    <html><body>
      <main><p>{LONG_ENGLISH}</p></main>
      <section class="more-from-us">{related}</section>
    </body></html>
    """

    text = clean_html(html, settings=settings())

    assert LONG_ENGLISH in text
    assert "A related headline" not in text


def test_inline_text_beside_child_paragraphs_is_not_dropped() -> None:
    """A wrapper that mixes its own text with <p> children keeps both."""
    html = f"""
    <div class="content">
      Lead sentence written directly inside the wrapper.
      <p>{LONG_ENGLISH}</p>
      Trailing sentence also written directly inside the wrapper.
    </div>
    """

    text = clean_html(html, settings=settings())

    assert "Lead sentence written directly inside the wrapper." in text
    assert LONG_ENGLISH in text
    assert "Trailing sentence also written directly inside the wrapper." in text


# --- 4/5/6. the body keeps its original language and is never translated ---


def test_english_article_stays_english() -> None:
    content = extract_article(
        url="https://openai.com/index/a",
        title="A new reasoning mode",
        feed_summary="A short teaser.",
        settings=settings(),
        fetch=lambda url, timeout=10.0: page(article_page(LONG_ENGLISH)),
    )

    assert content.language == "en"
    assert LONG_ENGLISH in content.text


def test_chinese_article_stays_chinese() -> None:
    content = extract_article(
        url="https://www.ithome.com/2026/09/a",
        title="新的推理模式",
        feed_summary="一句话摘要。",
        settings=settings(),
        fetch=lambda url, timeout=10.0: page(article_page(LONG_CHINESE)),
    )

    assert content.language == "zh"
    assert LONG_CHINESE in content.text


def test_extraction_never_translates_or_rewrites() -> None:
    """The stored body is byte-for-byte the source text, not a Chinese version."""
    content = extract_article(
        url="https://openai.com/index/a",
        title="A new reasoning mode",
        feed_body=f"<p>{LONG_ENGLISH}</p>",
        feed_summary=SHORT_SUMMARY,
        settings=settings(),
    )

    assert content.text == LONG_ENGLISH
    # No Chinese character appears anywhere in an English body.
    assert detect_language(content.text) == "en"


def test_language_detection_ignores_a_stray_foreign_character() -> None:
    text = "A mostly English paragraph about models, with one 中 character in it."

    assert detect_language(text) == "en"


# --- 7/8. full body in the database, trimmed input for the LLM ---


def test_llm_input_is_trimmed_but_the_stored_body_is_not() -> None:
    long_body = LONG_ENGLISH * 40
    content = extract_article(
        url="https://example.com/a",
        title="A new reasoning mode",
        feed_body=f"<p>{long_body}</p>",
        feed_summary=SHORT_SUMMARY,
        settings=settings(max_chars=100000),
    )

    trimmed = truncate_for_llm(content.text, 500)

    assert len(content.text) > 500
    assert len(trimmed) == 500
    assert content.text.startswith(trimmed)


def test_max_chars_caps_what_is_stored() -> None:
    content = extract_article(
        url="https://example.com/a",
        title="A new reasoning mode",
        feed_body=f"<p>{LONG_ENGLISH * 40}</p>",
        feed_summary="",
        settings=settings(max_chars=300),
    )

    assert len(content.text) <= 300


# --- 9/10/11/12/13. every fetch failure falls back ---


@pytest.mark.parametrize(
    "failure",
    [
        FetchError("HTTP 404", status=404),
        FetchError("HTTP 500", status=500),
        FetchError("request timed out"),
        FetchError("too many redirects (limit 5)"),
    ],
)
def test_http_failures_fall_back_to_the_rss_summary(failure: Exception) -> None:
    def fetch(url: str, *, timeout: float = 10.0):
        raise failure

    content = extract_article(
        url="https://example.com/a",
        title="A new reasoning mode",
        feed_summary=SHORT_SUMMARY,
        settings=settings(),
        fetch=fetch,
    )

    assert content.method == "rss_summary"
    assert content.text == SHORT_SUMMARY
    assert content.error


def test_non_html_response_falls_back() -> None:
    content = extract_article(
        url="https://example.com/a.pdf",
        title="A new reasoning mode",
        feed_summary=SHORT_SUMMARY,
        settings=settings(),
        fetch=lambda url, timeout=10.0: page("%PDF-1.7 binary", content_type="application/pdf"),
    )

    assert content.method == "rss_summary"
    assert content.text == SHORT_SUMMARY
    assert "not HTML" in (content.error or "")


def test_empty_body_falls_back() -> None:
    content = extract_article(
        url="https://example.com/a",
        title="A new reasoning mode",
        feed_summary=SHORT_SUMMARY,
        settings=settings(),
        fetch=lambda url, timeout=10.0: page("   "),
    )

    assert content.method == "rss_summary"
    assert "empty body" in (content.error or "")


def test_page_error_message_is_kept_for_the_log() -> None:
    content = extract_article(
        url="https://example.com/a",
        title="A new reasoning mode",
        feed_summary=SHORT_SUMMARY,
        settings=settings(),
        fetch=lambda url, timeout=10.0: page("", content_type="text/html") or None,
    )

    assert content.error


# --- 14. the cache prevents a second fetch ---


def test_cache_hit_avoids_fetching_the_page_again(tmp_path: Path) -> None:
    calls: list[str] = []

    def fetch(url: str, *, timeout: float = 10.0):
        calls.append(url)
        return page(article_page(LONG_ENGLISH))

    cache = ArticleContentCache(tmp_path / "articles")
    first = extract_article(
        url="https://example.com/a",
        canonical_url="https://example.com/a",
        title="A new reasoning mode",
        feed_summary=SHORT_SUMMARY,
        settings=settings(),
        cache=cache,
        fetch=fetch,
    )
    second = extract_article(
        url="https://example.com/a",
        canonical_url="https://example.com/a",
        title="A new reasoning mode",
        feed_summary=SHORT_SUMMARY,
        settings=settings(),
        cache=cache,
        fetch=fetch,
    )

    assert first.text == second.text
    assert second.from_cache is True
    assert len(calls) == 1


def test_a_failure_is_not_cached_so_it_can_be_retried(tmp_path: Path) -> None:
    cache = ArticleContentCache(tmp_path / "articles")
    attempts: list[int] = []

    def failing(url: str, *, timeout: float = 10.0):
        attempts.append(1)
        raise FetchError("HTTP 503", status=503)

    first = extract_article(
        url="https://example.com/a",
        canonical_url="https://example.com/a",
        title="A new reasoning mode",
        feed_summary=SHORT_SUMMARY,
        settings=settings(),
        cache=cache,
        fetch=failing,
    )
    second = extract_article(
        url="https://example.com/a",
        canonical_url="https://example.com/a",
        title="A new reasoning mode",
        feed_summary=SHORT_SUMMARY,
        settings=settings(),
        cache=cache,
        fetch=lambda url, timeout=10.0: page(article_page(LONG_ENGLISH)),
    )

    assert first.method == "rss_summary"
    assert second.method == "web"
    assert len(attempts) == 1


# --- 15. one article's failure does not affect the others ---


def test_one_failing_article_does_not_block_the_rest() -> None:
    articles = [
        make_raw(url="https://example.com/ok", title="Fine"),
        make_raw(url="https://example.com/bad", title="Broken"),
        make_raw(url="https://example.com/also-ok", title="Also fine", feed_body=f"<p>{LONG_ENGLISH}</p>"),
    ]

    def fetch(url: str, *, timeout: float = 10.0):
        if url.endswith("/bad"):
            raise FetchError("HTTP 403", status=403)
        return page(article_page(LONG_ENGLISH))

    enriched, stats = extract_articles(articles, settings=settings(), cache=None, fetch=fetch)

    assert stats.candidates == 3
    # Two bodies arrived, one page failed, and the failure did not spread.
    assert stats.web == 1
    assert stats.rss_full == 1
    assert stats.fallback == 1
    assert stats.failed == 1
    by_title = {item.title: item for item in enriched}
    assert LONG_ENGLISH in by_title["Fine"].content
    assert by_title["Broken"].content == SHORT_SUMMARY
    assert by_title["Also fine"].content_language == "en"


def test_extraction_stats_report_the_documented_shape() -> None:
    articles = [make_raw(feed_body=f"<p>{LONG_ENGLISH}</p>")]

    _, stats = extract_articles(articles, settings=settings(), cache=None)
    report = format_extraction_stats(stats)

    assert "Article extraction:" in report
    assert "Candidates: 1" in report
    assert "RSS full content: 1" in report
    # The default report never contains article text.
    assert LONG_ENGLISH[:40] not in report


def test_debug_report_lists_each_article_without_its_text() -> None:
    articles = [make_raw(title="A very specific headline", feed_body=f"<p>{LONG_ENGLISH}</p>")]

    _, stats = extract_articles(articles, settings=settings(), cache=None)
    report = format_extraction_stats(stats, debug=True)

    assert "OpenAI | RSS_FULL |" in report
    assert "A very specific headline" not in report
    assert LONG_ENGLISH[:40] not in report


def test_plain_text_feed_body_is_preserved() -> None:
    content = extract_article(
        url="https://example.com/a",
        title="A new reasoning mode",
        feed_body=LONG_ENGLISH,
        feed_summary=SHORT_SUMMARY,
        settings=settings(),
    )

    assert content.method == "rss_full"
    assert content.text == LONG_ENGLISH
