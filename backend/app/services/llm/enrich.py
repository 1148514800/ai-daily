from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timezone

from pydantic import ValidationError

from app.collectors.raw import RawArticle
from app.models import NewsItem
from app.pipelines.normalize import news_item_from_raw
from app.services.llm.cache import LLMCache
from app.services.llm.client import LLMClient, LLMCompletion, LLMError, parse_completion_json
from app.services.llm.prompts import PROMPT_VERSION, SYSTEM_PROMPT, build_user_prompt
from app.services.llm.schemas import ArticleEnrichment
from app.services.llm.settings import LLMSettings, load_llm_settings

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 2


@dataclass
class EnrichmentStats:
    candidates: int = 0
    llm_calls: int = 0
    cache_hits: int = 0
    success: int = 0
    fallback: int = 0
    failed: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    enabled: bool = False
    available: bool = False

    def add_usage(self, completion: LLMCompletion) -> None:
        if completion.input_tokens:
            self.input_tokens += completion.input_tokens
        if completion.output_tokens:
            self.output_tokens += completion.output_tokens


def sort_news_items(items: list[NewsItem]) -> list[NewsItem]:
    return sorted(
        items,
        key=lambda item: (
            item.importance_score is not None,
            item.importance_score if item.importance_score is not None else -1,
            item.published_at or "",
        ),
        reverse=True,
    )


def apply_enrichment(raw: RawArticle, enrichment: ArticleEnrichment) -> NewsItem:
    item = news_item_from_raw(raw)
    return item.model_copy(
        update={
            "title_cn": enrichment.title_cn.strip(),
            "summary": enrichment.summary_cn.strip(),
            "why_it_matters": enrichment.why_it_matters.strip(),
            "importance_score": enrichment.importance_score,
        }
    )


def _published_label(raw: RawArticle) -> str:
    published = raw.published_at
    if published is None:
        return ""
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return published.isoformat()


def _cache_key(cache: LLMCache, raw: RawArticle, settings: LLMSettings) -> str:
    return cache.make_key(
        canonical_url=raw.canonical_url or raw.url,
        title=raw.title,
        summary=raw.summary,
        model=settings.model,
        prompt_version=PROMPT_VERSION,
    )


def enrich_one(
    raw: RawArticle,
    *,
    settings: LLMSettings,
    cache: LLMCache,
    client: LLMClient,
    stats: EnrichmentStats,
) -> NewsItem:
    key = _cache_key(cache, raw, settings)
    cached = cache.get(key)
    if cached is not None:
        stats.cache_hits += 1
        return apply_enrichment(raw, cached)

    if not settings.available:
        stats.fallback += 1
        return news_item_from_raw(raw)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": build_user_prompt(
                source=raw.source,
                title_original=raw.title,
                rss_summary=raw.summary,
                published_at=_published_label(raw),
            ),
        },
    ]

    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        stats.llm_calls += 1
        try:
            completion = client.complete(messages)
            stats.add_usage(completion)
            payload = parse_completion_json(completion.text)
            enrichment = ArticleEnrichment.model_validate(payload)
            cache.set(key, enrichment)
            stats.success += 1
            return apply_enrichment(raw, enrichment)
        except (LLMError, ValidationError, ValueError, TypeError) as exc:
            last_error = exc
            logger.warning(
                "llm enrich failed attempt=%s/%s source=%s error=%s",
                attempt + 1,
                MAX_ATTEMPTS,
                raw.source_id,
                exc,
            )

    stats.failed += 1
    stats.fallback += 1
    logger.warning("llm fallback source=%s error=%s", raw.source_id, last_error)
    return news_item_from_raw(raw)


def enrich_articles(
    articles: list[RawArticle],
    *,
    settings: LLMSettings | None = None,
    cache: LLMCache | None = None,
    client: LLMClient | None = None,
) -> tuple[list[NewsItem], EnrichmentStats]:
    resolved = settings or load_llm_settings()
    stats = EnrichmentStats(
        candidates=len(articles),
        enabled=resolved.enabled,
        available=resolved.available,
    )
    resolved_cache = cache or LLMCache(resolved.cache_dir)
    resolved_client = client or LLMClient(resolved)

    items: list[NewsItem] = []
    for article in articles:
        try:
            items.append(
                enrich_one(
                    article,
                    settings=resolved,
                    cache=resolved_cache,
                    client=resolved_client,
                    stats=stats,
                )
            )
        except Exception:
            logger.exception("llm enrich crashed source=%s", article.source_id)
            stats.failed += 1
            stats.fallback += 1
            items.append(news_item_from_raw(article))

    return sort_news_items(items), stats
