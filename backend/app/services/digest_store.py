import logging
import os
from datetime import datetime, timezone

from app.collectors.rss import CollectResult, collect_all_sources
from app.config.timezone import digest_date_for, today_digest_date
from app.db.repositories import DigestRepository, GitHubRepository, NewsRepository
from app.db.session import new_session
from app.models import DailyDigest, GitHubProject, NewsItem
from app.pipelines.dedup import dedupe_articles
from app.pipelines.normalize import news_item_from_raw
from app.services.digest_window import (
    DEFAULT_WINDOW_HOURS,
    DigestWindow,
    as_utc,
    resolve_window,
)
from app.services.event_dedup import EventDedupStats, dedupe_events, log_event_dedup
from app.services.llm import EnrichmentStats, enrich_articles

logger = logging.getLogger(__name__)

DIGEST_TITLE = "今日 AI 日报"
EMPTY_DESCRIPTION = "今天还没有新的 AI 资讯。"
EVENT_DEBUG_ENV = "AI_DAILY_DEBUG_EVENT_DEDUP"


def _event_debug_enabled() -> bool:
    """Per-cluster event dedup logging, opt-in so default logs stay short."""
    return os.getenv(EVENT_DEBUG_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _iso(moment: datetime | None) -> str | None:
    return as_utc(moment).isoformat() if moment is not None else None


def _ordered_unique_by_id(items: list[NewsItem]) -> list[NewsItem]:
    """Drop repeated news ids while keeping first-seen order."""
    seen: set[str] = set()
    ordered: list[NewsItem] = []
    for item in items:
        if item.id in seen:
            continue
        seen.add(item.id)
        ordered.append(item)
    return ordered


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
        self.last_event_stats: EventDedupStats = EventDedupStats()
        self.last_saved_date: str | None = None
        self.last_news_count: int = 0
        self.last_github_count: int = 0
        self.last_kept_previous: bool = False

    def collect_news(
        self,
        window: DigestWindow,
        now: datetime | None = None,
        fetch_text=None,
    ) -> tuple[list[NewsItem], list[CollectResult]]:
        """Collect, filter, dedupe, and enrich the news for one issue window.

        Membership is decided by ``window_start < published_at <= window_end``,
        which already excludes future timestamps because ``window_end`` is never
        later than the refresh time. Does not touch the database.
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
        logger.info(
            "per-source: %s",
            " | ".join(
                f"{report.source_name}: {len(report.valid)}"
                if report.success
                else f"{report.source_name}: failed"
                for report in reports
            ),
        )

        merged = []
        for report in reports:
            merged.extend(report.valid)

        in_window = [article for article in merged if window.contains(article.published_at)]
        self.last_recent_count = len(in_window)
        if len(in_window) != len(merged):
            logger.info(
                "dropped %s articles outside the issue window start=%s end=%s kept=%s",
                len(merged) - len(in_window),
                window.start.isoformat(),
                window.end.isoformat(),
                len(in_window),
            )
        deduped = dedupe_articles(in_window)

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
        """Collect news and persist the current digest."""
        current = now or now_utc()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        date = digest_date_for(current)

        window = self.resolve_window(date, current)
        news_items, reports = self.collect_news(window, current, fetch_text)
        self.persist(
            date=date, window=window, news_items=news_items, github_projects=github_projects
        )
        return reports

    def resolve_window(self, date: str, current: datetime) -> DigestWindow:
        """Pick the issue window for the digest dated ``date``.

        An existing digest keeps its original ``window_start`` and only moves
        ``window_end`` forward, so re-refreshing the same day adds news instead of
        restarting the interval. A new digest continues from the previous
        successful cutoff, and the first one falls back to the last 24h.
        """
        session = new_session()
        try:
            repository = DigestRepository(session)
            window = repository.get_window(date)
            existing_start = window[0] if window is not None else None
            previous_end = repository.latest_window_end(date)
        finally:
            session.close()

        resolved = resolve_window(
            now=current,
            existing_start=existing_start,
            previous_end=previous_end,
            hours=DEFAULT_WINDOW_HOURS,
        )
        if previous_end is not None and existing_start is None and resolved.start != as_utc(previous_end):
            # The previous cutoff was unusable, so the day is back on the default
            # lookback. Surfaced once here rather than hidden in the fallback.
            logger.warning(
                "previous cutoff unusable date=%s previous_end=%s; using default %sh window",
                date,
                as_utc(previous_end).isoformat(),
                DEFAULT_WINDOW_HOURS,
            )
        return resolved

    def persist(
        self,
        *,
        date: str,
        window: DigestWindow,
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
            repository = DigestRepository(session)
            collected = self._within_window(window, news_items)
            # Nothing collected while a digest already exists means a collector
            # outage, not an empty day: keep the previous digest and report it.
            if not collected and repository.exists(date):
                session.rollback()
                self.last_kept_previous = True
                self.last_saved_date = None
                self.last_news_count = 0
                self.last_github_count = 0
                logger.warning("refresh produced no news; keeping existing digest date=%s", date)
                return False

            # A second refresh on the same day extends the digest instead of
            # replacing it, so earlier news stays linked, in its original order,
            # ahead of the newly collected items.
            candidates = _ordered_unique_by_id(repository.get_news(date) + collected)
            in_window = self._within_window(window, candidates)
            # Second dedup layer: one event, one linked entry. It runs on the
            # whole linked set rather than only this run's collection, so a
            # later refresh that re-collects one side of an event cannot
            # reintroduce the duplicate. Both original rows stay in
            # news_articles; only the digest link is folded.
            merged, event_stats = dedupe_events(in_window)
            self.last_event_stats = event_stats
            log_event_dedup(event_stats, debug=_event_debug_enabled())
            merged_ids = [item.id for item in merged]
            # Every collected article is stored, even one outside this window:
            # only the digest link is window-restricted, so an article is never
            # lost, it just stays unlinked until a window covers it.
            NewsRepository(session).upsert_many(news_items)
            projects = github_projects or []
            if projects:
                GitHubRepository(session).upsert_many(projects)
                github_ids = [project.id for project in projects]
            else:
                # A failed trending fetch must not erase projects already linked
                # to the day. Only a non-empty result replaces the ordering.
                github_ids = repository.get_github_ids(date)

            description = self._describe(merged)
            repository.save(
                date=date,
                title=DIGEST_TITLE,
                description=description,
                news_ids=merged_ids,
                github_ids=github_ids,
                window_start=window.start,
                window_end=window.end,
            )
            session.commit()
            self.last_kept_previous = False
            self.last_saved_date = date
            self.last_news_count = len(merged_ids)
            self.last_github_count = len(github_ids)
            return True
        except Exception:
            session.rollback()
            logger.exception("persisting digest failed date=%s", date)
            raise
        finally:
            session.close()

    def _within_window(self, window: DigestWindow, news_items: list[NewsItem]) -> list[NewsItem]:
        """Last line of defence before a digest-to-news link is written.

        The collector already filters by window, but every write path runs
        through here, so no caller can link news to a digest it does not belong
        to: only ``window_start < published_at <= window_end`` is linked.
        """
        kept = [item for item in news_items if window.contains(item.published_at)]
        dropped = len(news_items) - len(kept)
        if dropped:
            logger.warning(
                "refused %s news items outside the issue window start=%s end=%s",
                dropped,
                window.start.isoformat(),
                window.end.isoformat(),
            )
        return kept

    def _describe(self, merged: list[NewsItem]) -> str:
        """Summarise a digest by the sources of everything it links.

        Derived from the merged list, not just this run's collection, so an
        extended digest still describes its whole content.
        """
        if not merged:
            return EMPTY_DESCRIPTION
        sources = sorted({item.source for item in merged})
        return f"来自 {'、'.join(sources)} 的 {len(merged)} 条更新。"

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
                window_start=_iso(meta[2]),
                window_end=_iso(meta[3]),
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
