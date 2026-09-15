"""One-shot backfill of original article bodies for already stored articles.

Articles collected before Phase 10.5 have no ``content_original``. This job
reads the ``news_articles`` table, extracts the body of each article that still
misses one, and writes it back. Nothing else changes:

* no RSS or LLM call beyond the article page itself;
* no article is deleted and no digest is regenerated;
* the digest association (``daily_digest_news``) is never touched;
* an article that already has a body is skipped, so the job is repeatable and an
  interrupted run resumes where it stopped;
* one unreadable page only skips that article.

This job writes the database, so it refuses to run against the production one
unless ``--allow-production`` is given, and it backs that database up first.

Usage:

    uv run python -m app.jobs.backfill_article_content --limit 20
    uv run python -m app.jobs.backfill_article_content --date 2026-09-12
    uv run python -m app.jobs.backfill_article_content --limit 20 --dry-run
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import timezone
from typing import Callable

from app.collectors.raw import RawArticle
from app.config.maintenance import (
    EXIT_ABORTED,
    EXIT_REFUSED,
    MaintenanceError,
    ProductionGuardError,
    add_common_arguments,
    begin,
    format_header,
    SCHEMA_ABSENT,
    prepare_write,
    schema_state,
)
from app.db.models import NewsArticleRow
from app.db.repositories import NewsRepository
from app.db.session import init_db, new_session
from app.pipelines.urls import canonicalize_url
from app.services.article_extractor import (
    ArticleContentCache,
    ExtractionSettings,
    extract_article,
    load_extraction_settings,
)
from app.services.digest_window import historical_window


@dataclass
class BackfillResult:
    scanned: int = 0
    filled: int = 0
    skipped: int = 0
    failed: int = 0


def _as_raw(row: NewsArticleRow) -> RawArticle:
    """A stored row as the input the extractor expects."""
    published = row.published_at
    if published is not None and published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return RawArticle(
        source_id="",
        source=row.source or "",
        source_type=row.source_type or "",
        title=row.title_original or row.title_cn or "",
        url=row.url or "",
        canonical_url=row.canonical_url or canonicalize_url(row.url or ""),
        published_at=published,
        summary=row.summary or "",
    )


def window_bounds(date: str) -> tuple:
    """The UTC interval of the digest dated ``date``, from the configured cutoff."""
    window = historical_window(date)
    return (window.start, window.end)


def list_targets(limit: int | None = None, date: str | None = None) -> list[str]:
    """The ids a backfill would visit, read without extracting or writing.

    Used by ``--dry-run`` so the reported scope is the real one rather than a
    guess, and cheap because it selects ids only.
    """
    session = new_session()
    try:
        rows = NewsRepository(session).list_missing_content(
            limit=limit,
            published_between=window_bounds(date) if date else None,
        )
        return [row.id for row in rows]
    finally:
        session.close()


def backfill(
    *,
    limit: int | None = None,
    date: str | None = None,
    settings: ExtractionSettings | None = None,
    fetch=None,
    progress: Callable[[str], None] | None = None,
) -> BackfillResult:
    """Extract bodies for stored articles that still have none.

    Skips anything already extracted, so running it twice is a no-op.
    """
    resolved = settings or load_extraction_settings()
    cache = (
        ArticleContentCache(resolved.effective_cache_dir)
        if resolved.effective_cache_dir is not None
        else None
    )
    result = BackfillResult()
    session = new_session()
    try:
        repository = NewsRepository(session)
        rows = repository.list_missing_content(
            limit=limit,
            published_between=window_bounds(date) if date else None,
        )

        for row in rows:
            result.scanned += 1
            article = _as_raw(row)
            try:
                content = extract_article(
                    url=article.url,
                    canonical_url=article.canonical_url,
                    title=article.title,
                    feed_summary=article.summary,
                    settings=resolved,
                    cache=cache,
                    fetch=fetch,
                )
            except Exception as exc:  # one bad page never stops the run
                result.failed += 1
                if progress:
                    progress(f"FAILED {row.id} {exc.__class__.__name__}: {exc}")
                continue
            if not content.text:
                result.skipped += 1
                if progress:
                    progress(f"SKIPPED {row.id} {content.error or 'no content'}")
                continue
            repository.set_content(
                row.id,
                content=content.text,
                raw=content.raw,
                language=content.language,
                method=content.method,
            )
            session.commit()
            result.filled += 1
            if progress:
                progress(f"OK {row.id} {content.method} {len(content.text)} chars")
        return result
    finally:
        session.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill original article bodies from stored articles")
    parser.add_argument("--limit", type=int, default=None, help="stop after this many articles")
    parser.add_argument("--date", default=None, help="only articles inside this digest's window")
    parser.add_argument("--quiet", action="store_true", help="print only the final summary")
    add_common_arguments(parser)
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

    try:
        context = begin("backfill_article_content", args)
    except ProductionGuardError as exc:
        print(str(exc))
        return EXIT_REFUSED

    print(format_header(context))
    print("Article content backfill")
    if args.date:
        print(f"Date: {args.date}")
    if args.limit:
        print(f"Limit: {args.limit}")
    print()

    if not context.dry_run:
        try:
            prepare_write(context)
        except MaintenanceError as exc:
            print(f"Aborted: {exc}")
            return EXIT_ABORTED
        # Schema work belongs to a real write; a dry run must not touch the file.
        init_db()

    if context.dry_run:
        if schema_state(context.target) == SCHEMA_ABSENT:
            print("Dry run: no changes made")
            print("Would scan: 0")
            return 0
        targets = list_targets(limit=args.limit, date=args.date)
        for news_id in targets:
            print(f"WOULD EXTRACT {news_id}")
        print()
        print("Dry run: no changes made")
        print(f"Would scan: {len(targets)}")
        return 0

    def progress(line: str) -> None:
        if not args.quiet:
            print(line)

    result = backfill(limit=args.limit, date=args.date, progress=progress)
    print()
    print(f"Scanned: {result.scanned}")
    print(f"Filled: {result.filled}")
    print(f"Skipped: {result.skipped}")
    print(f"Failed: {result.failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
