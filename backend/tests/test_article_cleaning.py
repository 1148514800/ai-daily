"""Phase 10.11: cleaning a real page down to its article.

The detail screen used to show paragraphs of navbar, cookie banner, "related
articles" and footer around a short body. These tests pin the cleaning rules on
a page that carries all of that chrome at once, and pin the two boundaries that
matter more than the cleaning itself: a body that legitimately mentions cookies
is kept, and a source-specific selector wins over a bigger generic wrapper.
"""

from __future__ import annotations

from app.services.article_extractor import (
    ArticleContentCache,
    ExtractionSettings,
    clean_article_html,
    clean_html,
    extract_article,
)
from app.services.article_quality import GOOD

BODY_ONE = (
    "Cohere released North Small Translate today, an open-weight machine "
    "translation model aimed at regulated industries that need to keep their data "
    "inside their own infrastructure. The company says the model is available "
    "under a permissive licence and that it was trained on a curated mix of "
    "public and licensed parallel text."
)
BODY_COOKIE = (
    "The blog itself sets a cookie so that a reader's language choice survives a "
    "reload; the article's own text is stored separately and is never used to "
    "personalise anything else on the site. The team says the translation model "
    "runs the same code whether it is hosted or self-hosted."
)
BODY_THREE = (
    "Existing users can call the model through the same API endpoint and pay the "
    "same per-character rate, the company said, and the weights are published on "
    "the usual model hub for anyone who would rather self-host the model behind "
    "their own firewall."
)

CHROME_PAGE = f"""<!doctype html>
<html>
  <body>
    <nav class="navbar"><a href="/">Home</a><a href="/blog">Blog</a><a href="/pricing">Pricing</a></nav>
    <div class="cookie-banner"><p>Accept all cookies</p><button>Reject</button></div>
    <header class="site-header"><p>Subscribe to our newsletter</p></header>
    <main>
      <article class="blog-post-body">
        <h1>Introducing North Small Translate</h1>
        <p>{BODY_ONE}</p>
        <p>{BODY_COOKIE}</p>
        <p>{BODY_THREE}</p>
        <h2>Availability</h2>
        <ul>
          <li>Available today on the hosted API</li>
          <li>Weights published under a permissive licence</li>
        </ul>
      </article>
      <aside class="related-articles"><p>Related articles</p><a href="/blog/other">Another post</a></aside>
      <div class="share-buttons"><p>Share this article</p><a href="#">Twitter</a><a href="#">LinkedIn</a></div>
    </main>
    <footer><p>© 2026 Cohere. All rights reserved.</p><p>Privacy Policy</p><p>Terms of Use</p></footer>
    <script>window.analytics = {{"page": "blog"}};</script>
    <style>.hidden {{ display: none; }}</style>
  </body>
</html>"""


def settings(**kwargs) -> ExtractionSettings:
    values = dict(rss_full_min_chars=600, web_min_chars=200, max_chars=40000)
    values.update(kwargs)
    return ExtractionSettings(**values)


def test_the_body_survives_and_the_chrome_does_not() -> None:
    text = clean_html(CHROME_PAGE, title="Introducing North Small Translate", source_id="cohere")

    assert BODY_ONE in text
    assert BODY_THREE in text
    for junk in (
        "Accept all cookies",
        "Subscribe to our newsletter",
        "Related articles",
        "Share this article",
        "All rights reserved",
        "Privacy Policy",
        "Terms of Use",
        "window.analytics",
        ".hidden",
        "Home",
        "Pricing",
    ):
        assert junk not in text, junk


def test_structure_is_kept_as_light_markup() -> None:
    text = clean_html(CHROME_PAGE, source_id="cohere")

    assert "## Availability" in text
    assert "- Available today on the hosted API" in text
    assert "- Weights published under a permissive licence" in text


def test_the_repeated_hero_title_is_not_printed_twice() -> None:
    """The template prints the headline in the hero and again in the article."""
    page = f"""<html><body>
      <h1>Introducing North Small Translate</h1>
      <article class="blog-post-body">
        <h1>Introducing North Small Translate</h1>
        <p>{BODY_ONE}</p>
        <p>{BODY_THREE}</p>
      </article>
    </body></html>"""
    text = clean_html(page, title="Introducing North Small Translate")

    assert text.count("Introducing North Small Translate") == 0
    assert BODY_ONE in text


def test_a_body_that_mentions_cookies_is_kept() -> None:
    """Noise is decided by tag, class, id and role — never by the word "cookie"."""
    text = clean_html(CHROME_PAGE, source_id="cohere")

    assert BODY_COOKIE in text
    assert "cookie" in text


def test_the_cleaned_page_passes_the_quality_check() -> None:
    text, verdict = clean_article_html(CHROME_PAGE, source_id="cohere")

    assert verdict.verdict == GOOD
    assert verdict.usable is True
    assert BODY_ONE in text


def test_an_html_entity_and_stray_whitespace_are_normalised() -> None:
    page = f"""<html><body><article>
      <p>{BODY_ONE}</p>
      <p>Ampersand &amp; entity, curly &#8220;quotes&#8221; and a&nbsp;nbsp.</p>
      <p>{BODY_THREE}</p>
    </article></body></html>"""
    text = clean_html(page)

    assert "&amp;" not in text
    assert "&#8220;" not in text
    assert "&nbsp;" not in text
    assert "\u00a0" not in text
    # The entity is decoded into the character it stands for, not left as text.
    assert "curly \u201cquotes\u201d" in text
    assert "Ampersand & entity" in text


def test_a_source_specific_selector_beats_a_bigger_generic_wrapper() -> None:
    """The page's related-posts column is long; the article is still the body."""
    filler = " ".join(["A related story about something else entirely."] * 12)
    page = f"""<html><body><main>
      <article class="blog-post-body"><p>{BODY_ONE}</p><p>{BODY_THREE}</p></article>
      <section class="more"><p>{filler}</p><p>{filler}</p></section>
    </main></body></html>"""
    text = clean_html(page, source_id="cohere")

    assert BODY_ONE in text
    assert "related story" not in text


def test_a_page_without_a_container_still_yields_its_text() -> None:
    """Some sites wrap the whole article in one unstyled div."""
    page = f"<html><body><div>{BODY_ONE} {BODY_THREE}</div></body></html>"
    text = clean_html(page)

    assert BODY_ONE in text


def test_the_feed_body_wins_over_the_page_when_the_feed_has_the_article() -> None:
    """RSS full content is still the first choice; the page is never fetched."""
    calls: list[str] = []

    def fetch(url: str, *, timeout: float = 10.0):
        calls.append(url)
        raise AssertionError("the page must not be fetched when the feed has the body")

    content = extract_article(
        url="https://cohere.com/blog/x",
        title="Introducing North Small Translate",
        feed_body=f"<p>{BODY_ONE}</p><p>{BODY_COOKIE}</p><p>{BODY_THREE}</p>",
        feed_summary="A short teaser.",
        settings=settings(),
        fetch=fetch,
    )

    assert content.method == "rss_full"
    assert BODY_ONE in content.text
    assert calls == []


def test_the_cache_round_trips_the_quality_verdict(tmp_path) -> None:
    cache = ArticleContentCache(tmp_path / "cache")
    text, verdict = clean_article_html(CHROME_PAGE, source_id="cohere")
    stored = extract_article(
        url="https://cohere.com/blog/x",
        title="x",
        feed_body="",
        feed_summary="",
        settings=settings(),
        cache=cache,
        fetch=lambda url, *, timeout=10.0: _page(CHROME_PAGE),
    )

    assert stored.quality == GOOD
    assert stored.text == text
    assert verdict.verdict == GOOD


def _page(html: str):
    from app.collectors.http import FetchResult

    return FetchResult(url="https://cohere.com/blog/x", status=200, content_type="text/html", text=html)


def test_a_trailing_tag_list_is_dropped() -> None:
    """A "Topics" term list sits under the body; it is not part of the story.

    The block is plain markup with no <nav> or <footer> around it, so only the
    class name identifies it. Real pages produced exactly this on TechCrunch.
    """
    page = f"""<html><body><main>
      <article><p>{BODY_ONE}</p><p>{BODY_THREE}</p></article>
      <div class="wp-block-tc23-post-relevant-terms">
        <p>Topics</p><p>AI</p><p>Apple</p><p>Siri</p>
      </div>
    </main></body></html>"""
    text = clean_html(page, source_id="techcrunch-ai")

    assert BODY_ONE in text
    assert "Siri" not in text
    assert "Topics" not in text


def test_a_site_disclosure_block_is_dropped() -> None:
    """Affiliate / legal wording is about the publication, not the article."""
    page = f"""<html><body><main>
      <article><p>{BODY_ONE}</p><p>{BODY_THREE}</p></article>
      <p class="affiliate-disclaimer-text">
        When you purchase through links in our articles, we may earn a small
        commission. This doesn't affect our editorial independence.
      </p>
    </main></body></html>"""
    text = clean_html(page, source_id="techcrunch-ai")

    assert BODY_ONE in text
    assert "editorial independence" not in text
    assert "commission" not in text


def test_a_body_that_discusses_recommendations_is_kept() -> None:
    """The disclosure rule is structural: prose *about* it must survive."""
    sentence = (
        "The paper argues that affiliate disclaimers and recommendation systems "
        "change how readers judge a story, because a disclosure printed next to a "
        "link is read as an endorsement by the publication that hosts it."
    )
    page = f"<html><body><article><p>{BODY_ONE}</p><p>{sentence}</p></article></body></html>"
    text = clean_html(page)

    assert sentence in text
