"""Collectors for official sources that publish no usable feed.

Three sources list their news only in HTML. Each page is stable and public but
different in shape, so every source gets a small extractor here instead of one
generic guesser that would break silently. All of them return the same
``CollectResult`` as the RSS collector, so the pipeline stays source-agnostic.

An extractor returns ``(url, title, published_at)`` triples, or raises
``PageStructureError`` when the markup it depends on is gone. The two failure
modes stay distinct on purpose: a listing that is present but empty (nothing
published yet) behaves like an empty feed and succeeds with zero entries, while
a page that no longer contains the listing at all is reported as a failure so a
silent markup change shows up in the per-source stats instead of quietly
contributing nothing.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.collectors.http import DEFAULT_TIMEOUT, HTML_ACCEPT, fetch_text as http_fetch_text
from app.collectors.raw import CollectResult, RawArticle
from app.config.sources import NewsSource
from app.pipelines.normalize import news_item_from_raw
from app.pipelines.urls import canonicalize_url

ANTHROPIC_BASE = "https://www.anthropic.com"
DEEPSEEK_BASE = "https://api-docs.deepseek.com"
KIMI_BASE = "https://www.kimi.com"

ENGLISH_DATE_FORMATS = ("%b %d, %Y", "%B %d, %Y", "%b. %d, %Y")
ENGLISH_DATE_RE = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},\s*\d{4}\b"
)
DEEPSEEK_DATE_RE = re.compile(r"(\d{4}/\d{2}/\d{2})\s*$")
KIMI_ARTICLE_LIST = '\\"articleList\\"'
KIMI_ITEMS = '\\"items\\":'


class PageStructureError(Exception):
    """The page loaded but no longer contains the listing being parsed."""


def parse_english_date(raw: str) -> datetime | None:
    text = " ".join(str(raw).split())
    for fmt in ENGLISH_DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _unescape_payload(raw: str) -> str:
    """Turn an escaped Next.js flight payload fragment back into JSON."""
    return raw.replace("\\\\", "\\").replace('\\"', '"')


def _extract_json_array(text: str, start: int) -> str | None:
    """Return the balanced ``[...]`` literal starting at ``start``.

    A regex cannot do this safely because the objects contain escaped quotes and
    embedded ``]`` inside URLs, so the array is scanned bracket by bracket while
    skipping anything inside a string.
    """
    if start < 0 or start >= len(text) or text[start] != "[":
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def anthropic_entries(html: str) -> list[tuple[str, str, datetime]]:
    """Anthropic news index: every card is an ``/news/`` link with a ``<time>``."""
    soup = BeautifulSoup(html, "html.parser")
    anchors = soup.select('a[href^="/news/"]')
    if not anchors:
        raise PageStructureError("no /news/ links on the Anthropic index")

    entries: list[tuple[str, str, datetime]] = []
    for anchor in anchors:
        time_el = anchor.find("time")
        if time_el is None:
            continue
        published = parse_english_date(time_el.get_text(" ", strip=True))
        if published is None:
            continue
        heading = anchor.find(["h1", "h2", "h3", "h4", "h5", "h6"])
        if heading is not None:
            title = heading.get_text(" ", strip=True)
        else:
            title_el = anchor.select_one('[class*="title"]')
            title = title_el.get_text(" ", strip=True) if title_el is not None else ""
        if not title:
            continue
        entries.append((urljoin(ANTHROPIC_BASE, anchor["href"]), title, published))
    return entries


def kimi_entries(html: str) -> list[tuple[str, str, datetime]]:
    """Kimi research blog: the listing lives in an escaped flight payload."""
    marker = html.find(KIMI_ARTICLE_LIST)
    if marker < 0:
        raise PageStructureError("no article list in the Kimi blog payload")

    items_at = html.find(KIMI_ITEMS, marker)
    if items_at < 0:
        raise PageStructureError("no items array in the Kimi blog payload")
    # The payload escapes every quote, so decode before scanning for the array
    # brackets; otherwise escaped quotes would be read as string delimiters.
    decoded = _unescape_payload(html[items_at:])
    raw_array = _extract_json_array(decoded, decoded.find("["))
    if raw_array is None:
        raise PageStructureError("unterminated items array in the Kimi blog payload")
    try:
        items = json.loads(raw_array)
    except json.JSONDecodeError as exc:
        raise PageStructureError(f"unreadable items array in the Kimi blog payload: {exc}") from exc
    if not isinstance(items, list):
        raise PageStructureError("Kimi blog items payload is not a list")

    entries: list[tuple[str, str, datetime]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        raw_date = str(item.get("date") or "")
        try:
            published = datetime.strptime(raw_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        title = str(item.get("title") or "").strip()
        href = str(item.get("href") or "").strip()
        if not title or not href:
            continue
        entries.append((urljoin(KIMI_BASE, href), title, published))
    return entries


def deepseek_links(index_html: str) -> list[str]:
    """News page links from the DeepSeek docs index."""
    soup = BeautifulSoup(index_html, "html.parser")
    links: list[str] = []
    for anchor in soup.select('a[href^="/news/"]'):
        href = str(anchor.get("href") or "").strip()
        if href and href not in links:
            links.append(href)
    if not links:
        raise PageStructureError("no /news/ links on the DeepSeek docs index")
    return links


def deepseek_entries(page_html: str) -> list[tuple[str, str, datetime]]:
    """DeepSeek release notes: the docs sidebar lists title and date together."""
    soup = BeautifulSoup(page_html, "html.parser")
    entries: list[tuple[str, str, datetime]] = []
    for anchor in soup.select('a.menu__link[href^="/news/"]'):
        text = " ".join(anchor.get_text(" ", strip=True).split())
        match = DEEPSEEK_DATE_RE.search(text)
        if match is None:
            continue
        title = text[: match.start()].strip()
        if not title:
            continue
        published = datetime.strptime(match.group(1), "%Y/%m/%d").replace(tzinfo=timezone.utc)
        entries.append((urljoin(DEEPSEEK_BASE, anchor["href"]), title, published))
    return entries


def _result_from_entries(
    source: NewsSource,
    entries: list[tuple[str, str, datetime]],
    *,
    fetched: int,
) -> CollectResult:
    result = CollectResult(source_id=source.id, source_name=source.name)
    result.fetched = fetched
    seen: set[str] = set()
    for url, title, published in entries:
        canonical = canonicalize_url(url)
        if canonical in seen:
            result.skipped += 1
            continue
        seen.add(canonical)
        raw = RawArticle(
            source_id=source.id,
            source=source.name,
            source_type=source.source_type,
            title=title,
            url=url,
            canonical_url=canonical,
            published_at=published,
            summary="",
        )
        result.valid.append(raw)
        result.news_items.append(news_item_from_raw(raw))
    return result


def parse_html_page(source: NewsSource, *, index_html: str, page_html: str | None = None) -> CollectResult:
    """Parse already fetched HTML for a source. Split out so tests stay offline."""
    try:
        if source.id == "anthropic":
            entries = anthropic_entries(index_html)
        elif source.id == "kimi":
            entries = kimi_entries(index_html)
        elif source.id == "deepseek":
            entries = deepseek_entries(page_html or index_html)
        else:
            return CollectResult(
                source_id=source.id,
                source_name=source.name,
                success=False,
                error=f"no HTML extractor for source {source.id}",
            )
    except PageStructureError as exc:
        return CollectResult(
            source_id=source.id,
            source_name=source.name,
            success=False,
            error=str(exc),
        )
    except Exception as exc:  # a malformed page must never abort the refresh
        return CollectResult(
            source_id=source.id,
            source_name=source.name,
            success=False,
            error=f"HTML parse failed: {exc}",
        )

    return _result_from_entries(source, entries, fetched=len(entries))


def fetch_html(url: str, timeout: float = DEFAULT_TIMEOUT) -> str:
    return http_fetch_text(url, timeout=timeout, accept=HTML_ACCEPT)


def collect_html_source(
    source: NewsSource,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    fetch_text=None,
) -> CollectResult:
    fetch = fetch_text or fetch_html
    try:
        index_html = fetch(source.url, timeout=timeout)
    except Exception as exc:
        return CollectResult(
            source_id=source.id,
            source_name=source.name,
            success=False,
            error=str(exc) or exc.__class__.__name__,
        )

    if not index_html or not str(index_html).strip():
        return CollectResult(
            source_id=source.id,
            source_name=source.name,
            success=False,
            error="Empty HTML response",
        )

    page_html: str | None = None
    if source.id == "deepseek":
        try:
            links = deepseek_links(str(index_html))
        except PageStructureError as exc:
            return CollectResult(
                source_id=source.id,
                source_name=source.name,
                success=False,
                error=str(exc),
            )
        try:
            page_html = fetch(urljoin(DEEPSEEK_BASE, links[0]), timeout=timeout)
        except Exception as exc:
            return CollectResult(
                source_id=source.id,
                source_name=source.name,
                success=False,
                error=str(exc) or exc.__class__.__name__,
            )

    return parse_html_page(source, index_html=str(index_html), page_html=page_html)
