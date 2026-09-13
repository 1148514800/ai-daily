"""One-shot repair of daily digest membership for already stored articles.

A digest covers the issue window ``(window_start, window_end]`` rather than a
calendar day. This job re-derives each requested digest from the
``news_articles`` table only, so no RSS fetch and no LLM call happens and no
article is deleted.

Window sources, in order:

1. the digest's own stored ``window_start`` / ``window_end``;
2. for a first run, the window derived from the configured daily cutoff
   (``DAILY_REFRESH_HOUR`` in ``APP_TIMEZONE``): ``(cutoff(D-1), cutoff(D)]``.

Usage:

    uv run python -m app.jobs.rebuild_digests --dates 2026-09-12,2026-09-13
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime

from app.config.timezone import DIGEST_DATE_FORMAT, app_timezone_name
from app.db.repositories import DigestRepository, NewsRepository
from app.db.session import init_db, new_session
from app.models import NewsItem
from app.services.digest_store import DIGEST_TITLE, EMPTY_DESCRIPTION
from app.services.digest_window import DigestWindow, historical_window
from app.services.llm.enrich import sort_news_items

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
    """Keep only articles inside ``window``, newest first."""
    matching = [item for item in articles if window.contains(item.published_at)]
    # Same ordering rule as a normal refresh, so a rebuilt day reads the same.
    return sort_news_items(matching)


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


def rebuild_dates(dates: list[str]) -> list[RebuildResult]:
    """Recompute digest membership for ``dates`` from stored articles.

    A digest that already carries a window keeps it, so rebuilding is idempotent
    and never silently widens a digest that was built at a non-default time.
    """
    session = new_session()
    try:
        articles = NewsRepository(session).list_all()
        repository = DigestRepository(session)
        results: list[RebuildResult] = []
        for date in dates:
            window = _window_for(repository, date)
            before = [item.id for item in repository.get_news(date)]
            selected = articles_for_window(articles, window)
            selected_ids = [item.id for item in selected]
            # The window is always written, even for an empty day, so later
            # refreshes continue from this cutoff instead of a fixed lookback.
            repository.save(
                date=date,
                title=DIGEST_TITLE,
                description=_describe(selected, selected_ids),
                news_ids=selected_ids,
                github_ids=repository.get_github_ids(date),
                window_start=window.start,
                window_end=window.end,
            )
            results.append(
                RebuildResult(date=date, window=window, before=before, after=selected_ids)
            )
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

    init_db()
    print(f"Timezone: {app_timezone_name()}")
    print(f"Dates: {', '.join(dates)}")
    print()
    for result in rebuild_dates(dates):
        print(f"{result.date}: {len(result.before)} -> {len(result.after)}")
        print(f"  window: {result.window.start.isoformat()} .. {result.window.end.isoformat()}")
        if result.removed:
            print(f"  removed: {', '.join(result.removed)}")
        if result.added:
            print(f"  added: {', '.join(result.added)}")
        for news_id in result.after:
            print(f"  kept: {news_id}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
