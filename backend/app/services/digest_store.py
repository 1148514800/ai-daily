import logging
from datetime import datetime, timezone

from app.collectors.rss import (
    CollectResult,
    article_within_last_hours,
    belongs_to_digest_date,
    collect_all_sources,
)
from app.config.timezone import digest_date_for, digest_date_for_iso, today_digest_date
from app.db.repositories import DigestRepository, GitHubRepository, NewsRepository
from app.db.session import new_session
from app.models import DailyDigest, GitHubProject, NewsItem
from app.pipelines.dedup import dedupe_articles
from app.pipelines.normalize import news_item_from_raw
from app.services.llm import EnrichmentStats, enrich_articles

logger = logging.getLogger(__name__)

DIGEST_TITLE = "今日 AI 日报"
EMPTY_DESCRIPTION = "今天还没有新的 AI 资讯。"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def empty_digest(date: str) -> DailyDigest:
    return DailyDigest(
        date=date,
        title=DIGEST_TITLE,
        description=EMPTY_DESCRIPTION,
        news=[],
        github_projects=[],
    )


class DigestStore:
    """Collects, enriches, and persists the daily digest.

    The database is the source of truth: reads always come from SQLite, so a
    restart keeps previous digests and in-memory state stays tiny.
    """

    def __init__(self) -> None:
        self.last_error: str | None = None
        self.last_reports: list[CollectResult] = []
        self.last_recent_count: int = 0
        self.last_llm_stats: EnrichmentStats = EnrichmentStats()
        self.last_saved_date: str | None = None
        self.last_news_count: int = 0
        self.last_github_count: int = 0
        self.last_kept_previous: bool = False

    def collect_news(
        self,
        date: str,
        now: datetime | None = None,
        fetch_text=None,
    ) -> tuple[list[NewsItem], list[CollectResult]]:
        """Collect, filter, dedupe, and enrich news for one digest date.

        Two independent conditions must hold: the article is inside the rolling
        24h window (which also rejects future timestamps) *and* its
        APP_TIMEZONE calendar day is the digest date. The digest is a calendar
        day report, so a neighbouring day's article never leaks in. Does not
        touch the database.
        """
        current = now or now_utc()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)

        reports = collect_all_sources(fetch_text=fetch_text)
        self.last_reports = reports
        errors = [report.error for report in reports if report.error]
        self.last_error = "; ".join(errors) if errors else None
        for report in reports:
            logger.info(
                "source=%s success=%s fetched=%s valid=%s skipped=%s error=%s",
                report.source_id,
                report.success,
                report.fetched,
                len(report.valid),
                report.skipped,
                report.error,
            )

        merged = []
        for report in reports:
            merged.extend(report.valid)

        recent = [article for article in merged if article_within_last_hours(article, current)]
        dated = [article for article in recent if belongs_to_digest_date(article.published_at, date)]
        self.last_recent_count = len(recent)
        if len(dated) != len(recent):
            logger.info(
                "dropped %s articles outside digest date date=%s kept=%s window=%s",
                len(recent) - len(dated),
                date,
                len(dated),
                len(recent),
            )
        deduped = dedupe_articles(dated)

        try:
            news_items, llm_stats = enrich_articles(deduped)
        except Exception:
            logger.exception("llm enrichment failed; using original RSS content")
            news_items = [news_item_from_raw(article) for article in deduped]
            llm_stats = EnrichmentStats(
                candidates=len(deduped),
                fallback=len(deduped),
                failed=len(deduped),
            )
        self.last_llm_stats = llm_stats
        logger.info(
            "llm candidates=%s calls=%s cache_hits=%s success=%s fallback=%s failed=%s",
            llm_stats.candidates,
            llm_stats.llm_calls,
            llm_stats.cache_hits,
            llm_stats.success,
            llm_stats.fallback,
            llm_stats.failed,
        )
        return news_items, reports

    def refresh(
        self,
        now: datetime | None = None,
        fetch_text=None,
        github_projects: list[GitHubProject] | None = None,
    ) -> list[CollectResult]:
        """Collect news and persist the day's digest."""
        current = now or now_utc()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        date = digest_date_for(current)

        news_items, reports = self.collect_news(date, current, fetch_text)
        self.persist(date=date, news_items=news_items, github_projects=github_projects)
        return reports

    def persist(
        self,
        *,
        date: str,
        news_items: list[NewsItem],
        github_projects: list[GitHubProject] | None,
    ) -> bool:
        """Write news, GitHub projects, and the digest in one transaction.

        Returns False when an existing digest was kept because this refresh
        produced no news, so a temporary collector outage never erases a good
        digest. Any error rolls the whole write back.
        """
        session = new_session()
        try:
            linked = self._only_on_date(date, news_items)
            if not linked and DigestRepository(session).exists(date):
                session.rollback()
                self.last_kept_previous = True
                self.last_saved_date = None
                self.last_news_count = 0
                self.last_github_count = 0
                logger.warning("refresh produced no news; keeping existing digest date=%s", date)
                return False

            # Every collected article is stored, even one whose calendar day is
            # not this digest's date: only the digest link is day-restricted, so
            # an article is never lost because it arrived after its own day.
            NewsRepository(session).upsert_many(news_items)
            projects = github_projects or []
            repository = DigestRepository(session)
            if projects:
                GitHubRepository(session).upsert_many(projects)
                github_ids = [project.id for project in projects]
            else:
                # A failed trending fetch must not erase projects already linked
                # to the day. Only a non-empty result replaces the ordering.
                github_ids = repository.get_github_ids(date)

            sources = sorted({item.source for item in linked})
            description = (
                f"来自 {'、'.join(sources)} 的 {len(linked)} 条更新。"
                if linked
                else EMPTY_DESCRIPTION
            )
            repository.save(
                date=date,
                title=DIGEST_TITLE,
                description=description,
                news_ids=[item.id for item in linked],
                github_ids=github_ids,
            )
            session.commit()
            self.last_kept_previous = False
            self.last_saved_date = date
            self.last_news_count = len(linked)
            self.last_github_count = len(github_ids)
            return True
        except Exception:
            session.rollback()
            logger.exception("persisting digest failed date=%s", date)
            raise
        finally:
            session.close()

    def _only_on_date(self, date: str, news_items: list[NewsItem]) -> list[NewsItem]:
        """Last line of defence before a digest-to-news link is written.

        The collector already filters by calendar day, but every write path runs
        through here, so a future caller cannot reintroduce cross-day news: an
        article is only linked to the digest whose local date it belongs to.
        """
        kept = [item for item in news_items if digest_date_for_iso(item.published_at) == date]
        dropped = len(news_items) - len(kept)
        if dropped:
            logger.warning(
                "refused %s news items whose local date is not the digest date date=%s",
                dropped,
                date,
            )
        return kept

    def latest_date(self) -> str | None:
        session = new_session()
        try:
            return DigestRepository(session).latest_date()
        finally:
            session.close()

    def get_today(self) -> DailyDigest:
        """Return the latest stored digest, or an empty digest for today."""
        return self.get_digest(self.latest_date() or today_digest_date())

    def get_digest(self, date: str) -> DailyDigest:
        session = new_session()
        try:
            repository = DigestRepository(session)
            meta = repository.get_meta(date)
            if meta is None:
                return empty_digest(date)
            return DailyDigest(
                date=date,
                title=meta[0],
                description=meta[1],
                news=repository.get_news(date),
                github_projects=repository.get_github(date),
            )
        finally:
            session.close()

    def get_by_date(self, date: str) -> DailyDigest | None:
        session = new_session()
        try:
            if not DigestRepository(session).exists(date):
                return None
        finally:
            session.close()
        return self.get_digest(date)

    def get_github_projects(self, date: str) -> list[GitHubProject]:
        session = new_session()
        try:
            return DigestRepository(session).get_github(date)
        finally:
            session.close()

    def get_news(self, news_id: str) -> NewsItem | None:
        session = new_session()
        try:
            return NewsRepository(session).get(news_id)
        finally:
            session.close()

    def list_digest_summaries(self) -> list[tuple[str, str, int, int]]:
        session = new_session()
        try:
            return DigestRepository(session).list_summaries()
        finally:
            session.close()

    def stats(self) -> tuple[int, int, int]:
        session = new_session()
        try:
            return (
                DigestRepository(session).count(),
                NewsRepository(session).count(),
                GitHubRepository(session).count(),
            )
        finally:
            session.close()


store = DigestStore()
