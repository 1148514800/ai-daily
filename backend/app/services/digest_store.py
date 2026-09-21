import logging
import os
from datetime import datetime, timezone

from app.collectors.rss import CollectResult, collect_all_sources
from app.config.ranking import top_story_limit
from app.config.sources import NEWS_SOURCE_TYPES
from app.config.timezone import digest_date_for, today_digest_date
from app.db.repositories import (
    DigestRepository,
    DigestSummaryData,
    GitHubRepository,
    NewsRepository,
)
from app.db.session import new_session
from app.models import DailyDigest, GitHubProject, NewsContent, NewsDetail, NewsItem
from app.pipelines.dedup import dedupe_articles
from app.pipelines.normalize import news_item_from_raw
from app.services.digest_window import (
    DEFAULT_WINDOW_HOURS,
    DigestWindow,
    as_utc,
    resolve_window,
)
from app.services.event_dedup import EventDedupStats, dedupe_events, log_event_dedup
from app.services.media_selection import (
    MediaSelectionSettings,
    MediaSelectionStats,
    log_media_selection,
    media_debug_enabled,
    select_media_articles,
)
from app.services.news_ranker import (
    RankingStats,
    apply_ranking,
)
from app.services.news_search import SearchResults, search_articles
from app.services.web_discovery import DiscoveryStats, collect_web_discovery
from app.services.llm import EnrichmentStats, enrich_articles
from app.services.article_extractor import (
    ExtractionSettings,
    ExtractionStats,
    extract_articles,
    load_extraction_settings,
    log_extraction,
)

logger = logging.getLogger(__name__)

DIGEST_TITLE = "今日 AI 日报"
EMPTY_DESCRIPTION = "今天还没有新的 AI 资讯。"
EVENT_DEBUG_ENV = "AI_DAILY_DEBUG_EVENT_DEDUP"
EXTRACTION_DEBUG_ENV = "AI_DAILY_DEBUG_EXTRACTION"


def _event_debug_enabled() -> bool:
    """Per-cluster event dedup logging, opt-in so default logs stay short."""
    return os.getenv(EVENT_DEBUG_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _extraction_debug_enabled() -> bool:
    """Per-article extraction logging, opt-in so default logs stay short."""
    return os.getenv(EXTRACTION_DEBUG_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


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
        # The pipeline funnel, in the order the stages run. Kept as plain
        # counters so the refresh command can print where articles were lost
        # without re-deriving it from the reports (which only know their own
        # pre-window output).
        self.last_fetched_count: int = 0
        self.last_recent_count: int = 0
        self.last_deduped_count: int = 0
        # Survivors of event dedup by source class: what media selection sees,
        # and therefore what "media before selection" has to be measured on.
        self.last_type_counts: dict[str, int] = {}
        self.last_llm_stats: EnrichmentStats = EnrichmentStats()
        self.last_extraction_stats: ExtractionStats = ExtractionStats()
        self.last_event_stats: EventDedupStats = EventDedupStats()
        self.last_media_stats: MediaSelectionStats = MediaSelectionStats()
        self.last_ranking_stats: RankingStats = RankingStats()
        self.last_saved_date: str | None = None
        self.last_news_count: int = 0
        self.last_github_count: int = 0
        self.last_kept_previous: bool = False
        # Web Discovery is an addition to the refresh, not part of it: it is
        # reported separately and its failure never counts against the sources.
        self.last_discovery_stats: DiscoveryStats | None = None
        # Kept so a debug refresh can print exactly what was handed to the pipeline.
        self.last_discovery_candidates: list = []

    def collect_news(
        self,
        window: DigestWindow,
        now: datetime | None = None,
        fetch_text=None,
        fetch_page=None,
        extraction_settings: ExtractionSettings | None = None,
    ) -> tuple[list[NewsItem], list[CollectResult]]:
        """Collect, filter, dedupe, extract, and enrich the news for one window.

        Membership is decided by ``window_start < published_at <= window_end``,
        which already excludes future timestamps because ``window_end`` is never
        later than the refresh time. Does not touch the database.

        Order matters: extraction runs after the rule dedup so a page is fetched
        once per surviving article, and before enrichment so the LLM summarises
        the real body instead of a feed teaser.
        """
        current = now or now_utc()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)

        reports = collect_all_sources(fetch_text=fetch_text)

        # Web discovery runs beside the fixed sources and is appended to their
        # reports, so the rest of this method - and the whole downstream
        # pipeline - cannot tell the two apart. A discovered page is an ordinary
        # RawArticle from here on. Discovery never raises: a provider outage is
        # reported and the fixed sources carry the digest on their own.
        discovery = collect_web_discovery(current)
        self.last_discovery_stats = discovery.stats if discovery is not None else None
        self.last_discovery_candidates = list(discovery.candidates) if discovery is not None else []
        if discovery is not None:
            reports.append(discovery.report)

        self.last_reports = reports

        # A discovery outage is reported on its own line and kept out of the
        # sources' aggregate error. The two are different failures: a fixed feed
        # is part of the digest, while discovery is an addition that is allowed
        # to be missing.
        if discovery is not None and not discovery.report.success:
            logger.warning("web discovery failed: %s", discovery.report.error)

        errors = [
            report.error
            for report in reports
            if report.error and not report.discovery
        ]
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
        self.last_fetched_count = len(merged)
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
        self.last_deduped_count = len(deduped)

        # Original-language article bodies, fetched once per article. A failure
        # here only costs the body: the article continues with its RSS summary.
        try:
            extracted, extraction_stats = extract_articles(
                deduped,
                settings=extraction_settings or load_extraction_settings(),
                fetch=fetch_page,
            )
        except Exception:
            logger.exception("article extraction failed; using RSS summaries")
            extracted = deduped
            extraction_stats = ExtractionStats(candidates=len(deduped), failed=len(deduped))
        self.last_extraction_stats = extraction_stats
        log_extraction(extraction_stats, debug=_extraction_debug_enabled())

        try:
            news_items, llm_stats = enrich_articles(extracted)
        except Exception:
            logger.exception("llm enrichment failed; using original RSS content")
            news_items = [news_item_from_raw(article) for article in extracted]
            llm_stats = EnrichmentStats(
                candidates=len(extracted),
                fallback=len(extracted),
                failed=len(extracted),
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
        fetch_page=None,
        extraction_settings: ExtractionSettings | None = None,
    ) -> list[CollectResult]:
        """Collect news and persist the current digest."""
        current = now or now_utc()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        date = digest_date_for(current)

        window = self.resolve_window(date, current)
        news_items, reports = self.collect_news(
            window,
            current,
            fetch_text,
            fetch_page=fetch_page,
            extraction_settings=extraction_settings,
        )
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
        media_settings: MediaSelectionSettings | None = None,
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
            self.last_type_counts = {
                name: sum(1 for item in merged if item.source_type == name)
                for name in NEWS_SOURCE_TYPES
            }
            log_event_dedup(event_stats, debug=_event_debug_enabled())
            # Second-pass curation: event dedup has already picked the source
            # that represents each event, so a media story dropped here is one
            # whose event nothing first-party covered. Official and research
            # entries pass through untouched, and no article is deleted — only
            # the digest link is skipped.
            selected, media_stats = select_media_articles(
                merged, settings=media_settings or MediaSelectionSettings()
            )
            self.last_media_stats = media_stats
            log_media_selection(media_stats, debug=media_debug_enabled())
            # Ranking runs last so it sees one entry per event, and before the
            # write so the stored order *is* the reading order. It only reorders:
            # every surviving item is still linked, so nothing is dropped from
            # the tail of the digest.
            ranked_items, ranking, rank_stats = apply_ranking(
                selected,
                window_start=window.start,
                window_end=window.end,
                cluster_sizes=event_stats.cluster_sizes,
                top_story_limit=top_story_limit(),
            )
            self.last_ranking_stats = rank_stats
            merged_ids = [item.id for item in ranked_items]
            rank_scores = {entry.news_id: entry.rank_score for entry in ranking}
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

            # Described from what the digest actually links, so the summary can
            # never claim a source that curation removed.
            description = self._describe(selected)
            repository.save(
                date=date,
                title=DIGEST_TITLE,
                description=description,
                news_ids=merged_ids,
                github_ids=github_ids,
                window_start=window.start,
                window_end=window.end,
                rank_scores=rank_scores,
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

    def get_news_detail(self, news_id: str) -> NewsDetail | None:
        session = new_session()
        try:
            return NewsRepository(session).get_detail(news_id)
        finally:
            session.close()

    def get_news_content(self, news_id: str) -> NewsContent | None:
        """The original body of one article, read only when it is asked for."""
        session = new_session()
        try:
            return NewsRepository(session).get_content(news_id)
        finally:
            session.close()

    def list_digest_summaries(self) -> list[DigestSummaryData]:
        """Every stored digest, newest first, as counts plus its window."""
        session = new_session()
        try:
            return DigestRepository(session).list_summaries()
        finally:
            session.close()

    def search(self, query: str, *, limit: int | None = None, offset: int = 0) -> SearchResults:
        """Search every stored article. Reads only from SQLite."""
        session = new_session()
        try:
            return search_articles(session, query, limit=limit, offset=offset)
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
