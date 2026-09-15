from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from time import struct_time

import feedparser

from app.collectors.http import DEFAULT_TIMEOUT, RSS_ACCEPT, fetch_text as http_fetch_text
from app.collectors.html import collect_html_source
from app.collectors.raw import CollectResult, RawArticle
from app.config.sources import NewsSource, enabled_sources
from app.models import NewsItem
from app.pipelines.ai_filter import is_ai_related
from app.pipelines.normalize import news_item_from_raw
from app.pipelines.urls import canonicalize_url

DEFAULT_WINDOW_HOURS = 24


def fetch_rss_text(url: str, timeout: float = DEFAULT_TIMEOUT) -> str:
    return http_fetch_text(url, timeout=timeout, accept=RSS_ACCEPT)


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


def _entry_body(entry: dict) -> str:
    """The full article body when the feed carries one, otherwise "".

    ``content:encoded`` and Atom ``<content>`` are where a feed publishes the
    whole article; ``summary`` / ``description`` is usually a teaser. Both are
    kept verbatim and in their original language; nothing is translated or
    rewritten here.
    """
    parts: list[str] = []
    content = entry.get("content")
    if isinstance(content, list):
        for item in content:
            value = item.get("value") if isinstance(item, dict) else item
            if value:
                parts.append(str(value))
    elif content:
        parts.append(str(content))
    for key in ("content_encoded", "content_encoded_body"):
        value = entry.get(key)
        if value:
            parts.append(str(value))
    # Whether this is long enough to stand in for the whole article is the
    # extractor's call, using its configured threshold; the collector only
    # reports what the feed actually published.
    return max(parts, key=len) if parts else ""


def parse_feed(xml: str, source: NewsSource) -> CollectResult:
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

        # A feed wider than its AI section (Ars Technica's AI category still
        # carries gadget and business stories) is filtered before the entry can
        # reach dedupe, ranking or the LLM. Counted as skipped, not as an error:
        # dropping the non-AI part of a feed is the source working correctly.
        if source.requires_ai_filter and not is_ai_related(title, summary):
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
            feed_body=_entry_body(entry),
        )
        result.valid.append(raw)
        result.news_items.append(news_item_from_raw(raw))

    return result


def collect_source(
    source: NewsSource,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    fetch_text=None,
) -> CollectResult:
    if source.kind == "html":
        return collect_html_source(source, timeout=timeout, fetch_text=fetch_text)

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


def _as_utc(moment: datetime) -> datetime:
    """Read a naive datetime as UTC, matching how collectors store times."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def within_last_hours(item: NewsItem, now: datetime, hours: int = DEFAULT_WINDOW_HOURS) -> bool:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    try:
        published = datetime.fromisoformat(item.published_at)
    except ValueError:
        return False
    delta = _as_utc(now) - _as_utc(published)
    # A future timestamp yields a negative delta and must never be a candidate,
    # even though "now - published <= 24h" would happily accept it.
    return timedelta(0) <= delta <= timedelta(hours=hours)
