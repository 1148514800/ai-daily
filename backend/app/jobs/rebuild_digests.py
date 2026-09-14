"""One-shot repair of daily digest membership for already stored articles.

A digest covers the issue window ``(window_start, window_end]`` rather than a
calendar day. This job re-derives each requested digest from the
``news_articles`` table only, so no RSS fetch and no LLM call happens and no
article is deleted.

Window sources, in order:

1. the digest's own stored ``window_start`` / ``window_end``;
2. for a first run, the window derived from the configured daily cutoff
   (``DAILY_REFRESH_HOUR`` in ``APP_TIMEZONE``): ``(cutoff(D-1), cutoff(D)]``.

This job writes the database, so it refuses to run against the production one
unless ``--allow-production`` is given, and it backs that database up first.

Usage:

    uv run python -m app.jobs.rebuild_digests --dates 2026-09-12,2026-09-13
    uv run python -m app.jobs.rebuild_digests --dates 2026-09-13 --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime

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
from app.config.timezone import DIGEST_DATE_FORMAT, app_timezone_name
from app.db.repositories import DigestRepository, NewsRepository
from app.db.session import init_db, new_session
from app.models import NewsItem
from app.services.digest_store import DIGEST_TITLE, EMPTY_DESCRIPTION
from app.services.digest_window import DigestWindow, historical_window
from app.services.news_ranker import apply_ranking

logger = logging.getLogger(__name__)

SOURCE_SEPARATOR = "、"


@dataclass
class RebuildResult:
    date: str
    window: DigestWindow
    before: list[str] = field(default_factory=list)
    after: list[str] = field(default_factory=list)

    @property
    def added(self) -> list[str]:
        return [news_id for news_id in self.after if news_id not in self.before]

    @property
    def removed(self) -> list[str]:
        return [news_id for news_id in self.before if news_id not in self.after]


def parse_dates(raw: str) -> list[str]:
    """Parse and validate a comma-separated YYYY-MM-DD list, keeping order."""
    dates: list[str] = []
    for chunk in raw.split(","):
        value = chunk.strip()
        if not value:
            continue
        try:
            # strptime rejects 2026-13-40, which a plain slice check would allow.
            parsed = datetime.strptime(value, DIGEST_DATE_FORMAT)
        except ValueError as exc:
            raise ValueError(f"invalid date: {value}") from exc
        normalized = parsed.strftime(DIGEST_DATE_FORMAT)
        if normalized != value:
            raise ValueError(f"invalid date: {value}")
        if normalized not in dates:
            dates.append(normalized)
    if not dates:
        raise ValueError("no dates given")
    return dates


def articles_for_window(articles: list[NewsItem], window: DigestWindow) -> list[NewsItem]:
    """Keep only the articles inside ``window``, in digest reading order.

    A rebuild ranks with the same module a refresh uses, so a repaired day is
    ordered exactly like one collected normally. Event dedup is not re-run: it
    needs the full text of every report, and the linked set was already folded
    when the digest was first written.
    """
    matching = [item for item in articles if window.contains(item.published_at)]
    ordered, ranking, _stats = apply_ranking(
        matching, window_start=window.start, window_end=window.end
    )
    return ordered


def _window_for(repository: DigestRepository, date: str) -> DigestWindow:
    """The stored window of a digest, or the one the configured cutoff implies."""
    stored = repository.get_window(date)
    if stored is not None and stored[0] is not None and stored[1] is not None:
        window = DigestWindow(start=stored[0], end=stored[1])
        if window.valid:
            return window
    return historical_window(date)


def _describe(items: list[NewsItem], news_ids: list[str]) -> str:
    if not news_ids:
        return EMPTY_DESCRIPTION
    sources = sorted({item.source for item in items})
    source_list = SOURCE_SEPARATOR.join(sources)
    return f"来自 {source_list} 的 {len(news_ids)} 条更新。"


def rebuild_dates(dates: list[str], *, apply: bool = True) -> list[RebuildResult]:
    """Recompute digest membership for ``dates`` from stored articles.

    A digest that already carries a window keeps it, so rebuilding is idempotent
    and never silently widens a digest that was built at a non-default time.

    With ``apply=False`` the same diff is computed and returned but nothing is
    written, which is what ``--dry-run`` reports.
    """
    session = new_session()
    try:
        articles = NewsRepository(session).list_all()
        repository = DigestRepository(session)
        results: list[RebuildResult] = []
        for date in dates:
            window = _window_for(repository, date)
            before = [item.id for item in repository.get_news(date)]
            matching = [item for item in articles if window.contains(item.published_at)]
            selected, ranking, _stats = apply_ranking(
                matching, window_start=window.start, window_end=window.end
            )
            selected_ids = [item.id for item in selected]
            rank_scores = {entry.news_id: entry.rank_score for entry in ranking}
            # The window is always written, even for an empty day, so later
            # refreshes continue from this cutoff instead of a fixed lookback.
            if apply:
                repository.save(
                    date=date,
                    title=DIGEST_TITLE,
                    description=_describe(selected, selected_ids),
                    news_ids=selected_ids,
                    github_ids=repository.get_github_ids(date),
                    window_start=window.start,
                    window_end=window.end,
                    rank_scores=rank_scores,
                )
            results.append(
                RebuildResult(date=date, window=window, before=before, after=selected_ids)
            )
        if apply:
            session.commit()
        return results
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rebuild daily digest membership from stored articles")
    parser.add_argument("--dates", required=True, help="comma separated YYYY-MM-DD list")
    add_common_arguments(parser)
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

    try:
        dates = parse_dates(args.dates)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 2

    try:
        context = begin("rebuild_digests", args)
    except ProductionGuardError as exc:
        print(str(exc))
        return EXIT_REFUSED

    print(format_header(context))
    print(f"Timezone: {app_timezone_name()}")
    print(f"Dates: {', '.join(dates)}")
    print()

    if context.dry_run and schema_state(context.target) == SCHEMA_ABSENT:
        # Nothing to compare against: say so rather than failing on a table that
        # was never created, and leave the file alone.
        print("Dry run: no changes made")
        print("Database has no AI Daily schema yet.")
        return 0

    if not context.dry_run:
        try:
            prepare_write(context)
        except MaintenanceError as exc:
            print(f"Aborted: {exc}")
            return EXIT_ABORTED
        # Schema work is part of writing, so a dry run never calls this: it must
        # not create tables, columns or a search index.
        init_db()

    for result in rebuild_dates(dates, apply=not context.dry_run):
        print(f"{result.date}: {len(result.before)} -> {len(result.after)}")
        print(f"  window: {result.window.start.isoformat()} .. {result.window.end.isoformat()}")
        if result.removed:
            print(f"  removed: {', '.join(result.removed)}")
        if result.added:
            print(f"  added: {', '.join(result.added)}")
        for news_id in result.after:
            print(f"  kept: {news_id}")
        print()
    if context.dry_run:
        print("Dry run: no changes made")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
