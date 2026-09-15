"""Phase 10.5: the one-shot backfill for articles stored before extraction.

The job has to be safe to run on a real database: it fills only what is missing,
leaves the digest alone, and survives a page that cannot be read.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.collectors.http import FetchError, FetchResult
from app.db.repositories import DigestRepository, NewsRepository
from app.db.session import new_session
from app.jobs.backfill_article_content import backfill, main
from app.models import NewsCategory, NewsItem
from app.services.article_extractor import ExtractionSettings
from app.services.digest_window import DigestWindow
from tests.conftest import stored_body

UTC = timezone.utc

BODY = (
    "OpenAI introduced a new reasoning mode today that lets the model spend more "
    "time on a problem before answering. The company says the mode is available "
    "in the API immediately and that it improves results on multi-step tasks. "
    "It also published evaluation numbers comparing the new mode with the "
    "previous default, and said pricing is unchanged for the first month. "
    "Engineers described the change as a shift in how the model allocates "
    "compute rather than a new model release, and said the same weights are "
    "used throughout. Early users reported better results on long multi-step "
    "tool use while simple prompts became slower, so the mode stays opt-in."
)

PAGE = f"<html><body><article><p>{BODY}</p></article></body></html>"

# 2026-09-12 08:00 Asia/Shanghai in UTC, inside the window the tests write to.
PUBLISHED = datetime(2026, 9, 11, 22, 0, tzinfo=UTC)

WINDOW = DigestWindow(
    start=datetime(2026, 9, 10, 16, 0, tzinfo=UTC),
    end=datetime(2026, 9, 11, 16, 0, tzinfo=UTC),
)


def stored_article(index: int, *, digest_date: str = "2026-09-11") -> NewsItem:
    return NewsItem(
        id=f"rss-{index:04d}",
        title_cn=f"标题 {index}",
        title_original=f"Title {index}",
        summary=f"摘要 {index}",
        why_it_matters="",
        source="OpenAI",
        source_type="official",
        published_at=PUBLISHED.isoformat(),
        category=NewsCategory.highlight,
        tags=["OpenAI"],
        url=f"https://openai.com/index/{index}",
    )


def seed(count: int = 3, *, link_to_digest: bool = True) -> list[str]:
    """Store articles, optionally linking them to one digest."""
    session = new_session()
    try:
        items = [stored_article(index) for index in range(1, count + 1)]
        NewsRepository(session).upsert_many(items)
        if link_to_digest:
            DigestRepository(session).save(
                date="2026-09-11",
                title="今日 AI 日报",
                description="测试",
                news_ids=[item.id for item in items],
                github_ids=[],
                window_start=WINDOW.start,
                window_end=WINDOW.end,
            )
        session.commit()
        return [item.id for item in items]
    finally:
        session.close()


def settings(tmp_path: Path) -> ExtractionSettings:
    return ExtractionSettings(cache_dir=tmp_path / "article-cache")


def test_backfill_fills_bodies_for_stored_articles(tmp_path: Path) -> None:
    ids = seed(3)

    result = backfill(
        settings=settings(tmp_path),
        fetch=lambda url, timeout=10.0: FetchResult(
            url=url, status=200, content_type="text/html", text=PAGE
        ),
    )

    assert result.scanned == 3
    assert result.filled == 3
    session = new_session()
    try:
        for news_id in ids:
            stored = NewsRepository(session).get_detail(news_id)
            assert stored is not None
            assert BODY in stored_body(session, news_id)
            assert stored.content_language == "en"
            assert stored.has_content is True
    finally:
        session.close()


def test_backfill_does_not_touch_the_digest_association(tmp_path: Path) -> None:
    ids = seed(2)

    backfill(
        settings=settings(tmp_path),
        fetch=lambda url, timeout=10.0: FetchResult(
            url=url, status=200, content_type="text/html", text=PAGE
        ),
    )

    session = new_session()
    try:
        repository = DigestRepository(session)
        assert repository.get_news_ids("2026-09-11") == ids
        assert repository.count() == 1
    finally:
        session.close()


def test_backfill_is_repeatable_and_skips_extracted_articles(tmp_path: Path) -> None:
    seed(2)
    calls: list[str] = []

    def fetch(url: str, *, timeout: float = 10.0):
        calls.append(url)
        return FetchResult(url=url, status=200, content_type="text/html", text=PAGE)

    first = backfill(settings=settings(tmp_path), fetch=fetch)
    second = backfill(settings=settings(tmp_path), fetch=fetch)

    assert first.filled == 2
    assert second.scanned == 0
    assert len(calls) == 2


def test_backfill_respects_the_limit(tmp_path: Path) -> None:
    seed(3)

    result = backfill(
        limit=1,
        settings=settings(tmp_path),
        fetch=lambda url, timeout=10.0: FetchResult(
            url=url, status=200, content_type="text/html", text=PAGE
        ),
    )

    assert result.scanned == 1
    assert result.filled == 1


def test_one_failing_page_does_not_stop_the_backfill(tmp_path: Path) -> None:
    seed(3)

    def fetch(url: str, *, timeout: float = 10.0):
        if url.endswith("/2"):
            raise FetchError("HTTP 403", status=403)
        return FetchResult(url=url, status=200, content_type="text/html", text=PAGE)

    result = backfill(settings=settings(tmp_path), fetch=fetch)

    # The run completes and every article is accounted for.
    assert result.scanned == 3
    session = new_session()
    try:
        repository = NewsRepository(session)
        broken = repository.get_detail("rss-0002")
        healthy = repository.get_detail("rss-0001")
    finally:
        session.close()
    # The two readable articles got their real bodies; the blocked one fell back
    # to its RSS summary exactly as a normal refresh would, and is marked as a
    # fallback rather than silently looking like a successful extraction.
    assert BODY in stored_body(session, "rss-0001")
    assert healthy is not None and healthy.content_extraction_method == "web"
    assert broken is not None
    assert broken.content_extraction_method == "rss_summary"
    assert stored_body(session, "rss-0002") == "摘要 2"


def test_backfill_cli_reports_a_summary(tmp_path: Path, monkeypatch, capsys) -> None:
    seed(1)
    monkeypatch.setenv("ARTICLE_CACHE_DIR", str(tmp_path / "article-cache"))
    monkeypatch.setattr(
        "app.jobs.backfill_article_content.extract_article",
        lambda **kwargs: __import__(
            "app.services.article_extractor", fromlist=["ArticleContent"]
        ).ArticleContent(text=BODY, language="en", method="web"),
    )

    code = main(["--limit", "1"])
    output = capsys.readouterr().out

    assert code == 0
    assert "Filled: 1" in output
