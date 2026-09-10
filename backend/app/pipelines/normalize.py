import hashlib
from datetime import timezone

from app.collectors.raw import RawArticle
from app.models import NewsCategory, NewsItem
from app.pipelines.urls import canonicalize_url


def stable_news_id(url: str) -> str:
    canonical = canonicalize_url(url)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"rss-{digest}"


def news_item_from_raw(raw: RawArticle) -> NewsItem:
    published = raw.published_at
    if published is not None and published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    published_at = published.isoformat() if published is not None else ""

    return NewsItem(
        id=stable_news_id(raw.canonical_url or raw.url),
        title_cn=raw.title,
        title_original=raw.title,
        summary=raw.summary,
        why_it_matters="",
        source=raw.source,
        source_type=raw.source_type,
        published_at=published_at,
        category=NewsCategory.highlight,
        tags=[raw.source],
        url=raw.url,
    )
