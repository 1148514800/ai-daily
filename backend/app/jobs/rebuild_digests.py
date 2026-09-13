"""One-shot repair of daily digest membership for already stored articles.

The rolling 24h window used to let a future or neighbouring-day article into a
digest. This job re-derives each requested digest from the ``news_articles``
table only, so no RSS fetch and no LLM call happens and no article is deleted.

Usage:

    uv run python -m app.jobs.rebuild_digests --dates 2026-09-12,2026-09-13
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime

from app.collectors.rss import belongs_to_digest_date
from app.config.timezone import DIGEST_DATE_FORMAT, app_timezone_name
from app.db.repositories import DigestRepository, NewsRepository
from app.db.session import init_db, new_session
from app.models import NewsItem
from app.services.digest_store import DIGEST_TITLE, EMPTY_DESCRIPTION
from app.services.llm.enrich import sort_news_items

logger = logging.getLogger(__name__)

SOURCE_SEPARATOR = "、"


def _published_at(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@dataclass
class RebuildResult:
    date: str
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


def articles_for_date(articles: list[NewsItem], date: str) -> list[NewsItem]:
    """Keep only articles whose published_at local date is exactly ``date``."""
    matching = [
        item for item in articles if belongs_to_digest_date(_published_at(item.published_at), date)
    ]
    # Same ordering rule as a normal refresh, so a rebuilt day reads the same.
    return sort_news_items(matching)


def rebuild_dates(dates: list[str]) -> list[RebuildResult]:
    """Recompute digest membership for ``dates`` from stored articles."""
    session = new_session()
    try:
        articles = NewsRepository(session).list_all()
        repository = DigestRepository(session)
        results: list[RebuildResult] = []
        for date in dates:
            before = [item.id for item in repository.get_news(date)]
            selected = articles_for_date(articles, date)
            if not selected:
                # Nothing belongs to this day, so drop the day's stale links
                # instead of leaving a digest that points at other days' news.
                if before:
                    repository.save(
                        date=date,
                        title=DIGEST_TITLE,
                        description=EMPTY_DESCRIPTION,
                        news_ids=[],
                        github_ids=repository.get_github_ids(date),
                    )
                results.append(RebuildResult(date=date, before=before, after=[]))
                continue

            sources = sorted({item.source for item in selected})
            source_list = SOURCE_SEPARATOR.join(sources)
            description = f"来自 {source_list} 的 {len(selected)} 条更新。"
            repository.save(
                date=date,
                title=DIGEST_TITLE,
                description=description,
                news_ids=[item.id for item in selected],
                github_ids=repository.get_github_ids(date),
            )
            results.append(RebuildResult(date=date, before=before, after=[item.id for item in selected]))
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
