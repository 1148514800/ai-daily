from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from time import struct_time

import feedparser
import httpx

from app.collectors.raw import RawArticle
from app.config.sources import RSSSource, enabled_sources
from app.models import NewsItem
from app.pipelines.normalize import news_item_from_raw
from app.pipelines.urls import canonicalize_url

DEFAULT_TIMEOUT = 10.0
USER_AGENT = "ai-daily/0.1 (+https://github.com/1148514800/ai-daily)"


@dataclass
class CollectResult:
    source_id: str = ""
    source_name: str = ""
    success: bool = True
    fetched: int = 0
    valid: list[RawArticle] = field(default_factory=list)
    skipped: int = 0
    news_items: list[NewsItem] = field(default_factory=list)
    error: str | None = None


def fetch_rss_text(url: str, timeout: float = DEFAULT_TIMEOUT) -> str:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"}
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.text


def _parse_datetime(raw: str) -> datetime | None:
    text = raw.strip()
    if not text:
        return None
    try:
        value = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        value = None
    if value is None:
        try:
            value = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _published_at(entry: dict) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if isinstance(parsed, struct_time):
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    raw = entry.get("published") or entry.get("updated")
    if not raw:
        return None
    return _parse_datetime(str(raw))


def _http_url(value: object) -> str:
    text = str(value or "").strip()
    if text.startswith("http://") or text.startswith("https://"):
        return text
    return ""


def _entry_url(entry: dict) -> str:
    direct = _http_url(entry.get("link"))
    if direct:
        return direct
    for item in entry.get("links") or []:
        href = item.get("href") if isinstance(item, dict) else item
        found = _http_url(href)
        if found:
            return found
    return _http_url(entry.get("id") or entry.get("guid"))


def parse_feed(xml: str, source: RSSSource) -> CollectResult:
    result = CollectResult(source_id=source.id, source_name=source.name)
    try:
        parsed = feedparser.parse(xml)
    except Exception:
        result.success = False
        result.error = "RSS parse failed"
        return result

    entries = list(getattr(parsed, "entries", []) or [])
    result.fetched = len(entries)

    if not entries and getattr(parsed, "bozo", False):
        result.success = False
        result.error = "RSS parse failed"
        return result

    for entry in entries:
        title = str(entry.get("title") or "").strip()
        url = _entry_url(entry)
        summary = str(entry.get("summary") or entry.get("description") or "").strip()
        published_at = _published_at(entry)

        if not title or not url or published_at is None:
            result.skipped += 1
            continue

        raw = RawArticle(
            source_id=source.id,
            source=source.name,
            source_type=source.source_type,
            title=title,
            url=url,
            canonical_url=canonicalize_url(url),
            published_at=published_at,
            summary=summary,
        )
        result.valid.append(raw)
        result.news_items.append(news_item_from_raw(raw))

    return result


def collect_source(
    source: RSSSource,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    fetch_text=None,
) -> CollectResult:
    fetch = fetch_text or fetch_rss_text
    try:
        xml = fetch(source.url, timeout=timeout)
    except Exception as exc:
        return CollectResult(
            source_id=source.id,
            source_name=source.name,
            success=False,
            error=str(exc) or exc.__class__.__name__,
        )

    if not xml or not str(xml).strip():
        return CollectResult(
            source_id=source.id,
            source_name=source.name,
            success=False,
            error="Empty RSS response",
        )

    return parse_feed(str(xml), source)


def collect_all_sources(*, timeout: float = DEFAULT_TIMEOUT, fetch_text=None) -> list[CollectResult]:
    results: list[CollectResult] = []
    for source in enabled_sources():
        try:
            result = collect_source(source, timeout=timeout, fetch_text=fetch_text)
        except Exception as exc:
            result = CollectResult(
                source_id=source.id,
                source_name=source.name,
                success=False,
                error=str(exc) or exc.__class__.__name__,
            )
        results.append(result)
    return results


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


def article_within_last_hours(article: RawArticle, now: datetime, hours: int = 24) -> bool:
    if article.published_at is None:
        return False
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    published = article.published_at
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return now - published <= timedelta(hours=hours)
