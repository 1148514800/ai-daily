import logging
from datetime import datetime, timezone

from app.collectors.rss import CollectResult, article_within_last_hours, collect_all_sources
from app.models import DailyDigest, NewsItem
from app.pipelines.dedup import dedupe_articles
from app.pipelines.normalize import news_item_from_raw
from app.services.llm import EnrichmentStats, enrich_articles

logger = logging.getLogger(__name__)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def empty_digest(date: str) -> DailyDigest:
    return DailyDigest(
        date=date,
        title="今日 AI 日报",
        description="今天还没有新的 AI 资讯。",
        news=[],
        github_projects=[],
    )


class DigestStore:
    def __init__(self) -> None:
        self.digest: DailyDigest | None = None
        self.news_by_id: dict[str, NewsItem] = {}
        self.last_error: str | None = None
        self.last_reports: list[CollectResult] = []
        self.last_recent_count: int = 0
        self.last_llm_stats: EnrichmentStats = EnrichmentStats()

    def refresh(self, now: datetime | None = None, fetch_text=None) -> list[CollectResult]:
        current = now or now_utc()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        date = current.date().isoformat()

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
        self.last_recent_count = len(recent)
        deduped = dedupe_articles(recent)

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
            "llm candidates=%s calls=%s cache_hits=%s success=%s fallback=%s failed=%s input_tokens=%s output_tokens=%s",
            llm_stats.candidates,
            llm_stats.llm_calls,
            llm_stats.cache_hits,
            llm_stats.success,
            llm_stats.fallback,
            llm_stats.failed,
            llm_stats.input_tokens,
            llm_stats.output_tokens,
        )

        sources = sorted({item.source for item in news_items})
        if news_items:
            description = f"来自 {'、'.join(sources)} 的 {len(news_items)} 条更新。"
        else:
            description = "今天还没有新的 AI 资讯。"

        self.news_by_id = {item.id: item for item in news_items}
        self.digest = DailyDigest(
            date=date,
            title="今日 AI 日报",
            description=description,
            news=news_items,
            github_projects=[],
        )
        return reports

    def get_today(self) -> DailyDigest:
        if self.digest is None:
            return empty_digest(now_utc().date().isoformat())
        return self.digest

    def get_by_date(self, date: str) -> DailyDigest | None:
        digest = self.get_today()
        if digest.date == date:
            return digest
        return None

    def get_news(self, news_id: str) -> NewsItem | None:
        return self.news_by_id.get(news_id)


store = DigestStore()
