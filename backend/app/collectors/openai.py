from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from time import struct_time

import feedparser
import httpx

from app.collectors.raw import RawArticle
from app.pipelines.normalize import news_item_from_raw
from app.models import NewsItem

OPENAI_RSS_URL = "https://openai.com/news/rss.xml"
DEFAULT_TIMEOUT = 10.0
USER_AGENT = "ai-daily/0.1 (+https://github.com/1148514800/ai-daily)"


@dataclass
class CollectResult:
    fetched: int = 0
    valid: list[RawArticle] = field(default_factory=list)
    skipped: int = 0
    news_items: list[NewsItem] = field(default_factory=list)
    error: str | None = None


def fetch_rss_text(url: str = OPENAI_RSS_URL, timeout: float = DEFAULT_TIMEOUT) -> str:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml"}
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.text


def _published_at(entry: dict) -> datetime | None:
    parsed = entry.get("published_parsed")
    if isinstance(parsed, struct_time):
        try:
            return datetime(*parsed[:6], tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return None

    raw = entry.get("published")
    if not raw:
        return None
    try:
        value = parsedate_to_datetime(str(raw))
    except (TypeError, ValueError, IndexError):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def parse_openai_feed(xml: str) -> CollectResult:
    result = CollectResult()
    try:
        parsed = feedparser.parse(xml)
    except Exception:
        result.error = "RSS parse failed"
        return result

    entries = list(getattr(parsed, "entries", []) or [])
    result.fetched = len(entries)

    if not entries and getattr(parsed, "bozo", False):
        result.error = "RSS parse failed"
        return result

    for entry in entries:
        title = str(entry.get("title") or "").strip()
        url = str(entry.get("link") or entry.get("id") or "").strip()
        summary = str(entry.get("summary") or entry.get("description") or "").strip()
        published_at = _published_at(entry)

        if not title or not url or published_at is None:
            result.skipped += 1
            continue

        raw = RawArticle(
            source="OpenAI",
            title=title,
            url=url,
            published_at=published_at,
            summary=summary,
        )
        result.valid.append(raw)
        result.news_items.append(news_item_from_raw(raw))

    return result


def collect_openai_news(
    *,
    url: str = OPENAI_RSS_URL,
    timeout: float = DEFAULT_TIMEOUT,
    fetch_text=None,
) -> CollectResult:
    fetch = fetch_text or fetch_rss_text
    try:
        xml = fetch(url, timeout=timeout)
    except Exception as exc:
        return CollectResult(error=str(exc) or exc.__class__.__name__)

    if not xml or not str(xml).strip():
        return CollectResult(error="Empty RSS response")

    return parse_openai_feed(str(xml))


def within_last_hours(item: NewsItem, now: datetime, hours: int = 24) -> bool:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    try:
        published = datetime.fromisoformat(item.published_at)
    except ValueError:
        return False
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return now - published <= timedelta(hours=hours)


def main() -> None:
    from datetime import timedelta

    result = collect_openai_news()
    now = datetime.now(timezone.utc)
    recent = [
        item
        for item in result.news_items
        if item.published_at
        and now - datetime.fromisoformat(item.published_at) <= timedelta(hours=24)
    ]

    print(f"Fetched: {result.fetched}")
    print(f"Valid: {len(result.valid)}")
    print(f"Skipped: {result.skipped}")
    if result.error:
        print(f"Error: {result.error}")
    print(f"Last 24h: {len(recent)}")
    print()
    preview = sorted(result.news_items, key=lambda item: item.published_at, reverse=True)[:8]
    for item in preview:
        print(f"{item.published_at} | {item.title_original}")


if __name__ == "__main__":
    main()
