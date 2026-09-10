import hashlib
from datetime import timezone

from app.collectors.raw import RawArticle
from app.models import NewsCategory, NewsItem

SOURCE_NAME = "OpenAI"
SOURCE_TYPE = "official"


def stable_news_id(url: str) -> str:
    digest = hashlib.sha256(url.strip().encode("utf-8")).hexdigest()[:16]
    return f"openai-{digest}"


def news_item_from_raw(raw: RawArticle) -> NewsItem:
    published = raw.published_at
    if published is not None and published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    published_at = published.isoformat() if published is not None else ""

    return NewsItem(
        id=stable_news_id(raw.url),
        title_cn=raw.title,
        title_original=raw.title,
        summary=raw.summary,
        why_it_matters="",
        source=SOURCE_NAME,
        source_type=SOURCE_TYPE,
        published_at=published_at,
        category=NewsCategory.highlight,
        tags=["OpenAI"],
        url=raw.url,
    )
