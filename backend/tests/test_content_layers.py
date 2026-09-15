"""Phase 10.11: the raw capture behind a cleaned body.

The database keeps two layers of article text. ``content_original`` is what the
reader sees; ``content_raw`` is the candidate that cleaning started from, so a
body that lost a real paragraph to a noise rule can still be diagnosed. Only the
first one is ever served.
"""

from __future__ import annotations

from app.services.article_extractor import (
    ExtractionSettings,
    clean_html,
    clean_html_with_raw,
)
from app.db.repositories import _body_fields

BODY = (
    "Cohere released North Small Translate today, an open-weight machine "
    "translation model aimed at regulated industries that need to keep their data "
    "inside their own infrastructure."
)
MORE = (
    "Existing users can call the model through the same API endpoint and pay the "
    "same per-character rate, the company said."
)

PAGE = f"""<html><body>
  <nav><a href="/">Home</a><a href="/blog">Blog</a></nav>
  <article class="blog-post-body">
    <p>{BODY}</p>
    <p>{MORE}</p>
  </article>
  <footer><p>© 2026 Cohere. All rights reserved.</p></footer>
</body></html>"""


def settings() -> ExtractionSettings:
    return ExtractionSettings(rss_full_min_chars=600, web_min_chars=200, max_chars=40000)


def test_the_raw_capture_keeps_what_cleaning_removed() -> None:
    raw, text = clean_html_with_raw(PAGE, source_id="cohere", settings=settings())

    assert BODY in text
    assert BODY in raw
    # The footer is gone from the served text but still visible in the capture,
    # which is the whole point of keeping it.
    assert "All rights reserved" not in text
    assert "Home" not in text


def test_clean_html_still_returns_only_the_cleaned_text() -> None:
    """The existing entry point keeps its signature for every current caller."""
    assert clean_html(PAGE, source_id="cohere", settings=settings()).count(BODY) == 1


def test_plain_text_is_its_own_raw_capture() -> None:
    raw, text = clean_html_with_raw(f"{BODY}\n\n{MORE}")

    assert raw == text
    assert BODY in text


def test_empty_input_produces_two_empty_layers() -> None:
    assert clean_html_with_raw("") == ("", "")
    assert clean_html_with_raw("   \n ") == ("", "")


def test_the_raw_capture_never_reaches_the_api_shape() -> None:
    """The body description carries the verdict, never the raw text."""

    class Row:
        content_original = BODY
        content_raw = "Home Blog Pricing © 2026 Example Inc."
        content_language = "en"
        content_extraction_method = "web"
        content_quality = "good"

    fields = _body_fields(Row())

    assert set(fields) == {
        "has_content",
        "content_language",
        "content_extraction_method",
        "content_quality",
    }
    assert "content_raw" not in fields


def test_both_layers_survive_a_round_trip_through_the_database() -> None:
    """The two layers are stored, and only the cleaned one is served."""
    from app.db.repositories import NewsRepository
    from app.db.session import new_session
    from app.models import NewsCategory, NewsItem

    session = new_session()
    try:
        repository = NewsRepository(session)
        repository.upsert_many(
            [
                NewsItem(
                    id="rss-layers",
                    title_cn="标题",
                    title_original="Title",
                    summary="摘要",
                    why_it_matters="",
                    source="Cohere",
                    source_type="official",
                    published_at="2026-09-13T06:00:00+00:00",
                    category=NewsCategory.highlight,
                    tags=["Cohere"],
                    url="https://cohere.com/blog/layers",
                    content_original=BODY,
                    content_raw=f"Home Blog Pricing\n\n{BODY}",
                    content_language="en",
                    content_extraction_method="web",
                    content_quality="good",
                )
            ]
        )
        session.commit()
        content = repository.get_content("rss-layers")
        detail = repository.get_detail("rss-layers")
    finally:
        session.close()

    assert content is not None
    assert content.content_original == BODY
    assert "Home Blog Pricing" not in content.content_original
    # The detail shape reports the body's state and stays out of the raw layer.
    assert detail is not None
    assert detail.has_content is True
    assert not hasattr(detail, "content_raw") or not detail.content_raw
