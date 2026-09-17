"""Collectors for official sources that publish no usable feed.

Some sources list their news only in HTML. Each page is stable and public but
different in shape, so every source gets a small extractor here instead of one
generic guesser that would break silently. All of them return the same
``CollectResult`` as the RSS collector, so the pipeline stays source-agnostic.

Every extractor is independent: a Mistral or Cursor markup change is reported as
that one source failing and cannot affect OpenAI, Anthropic or any other.

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

import httpx

from app.collectors.http import (
    DEFAULT_TIMEOUT,
    HTML_ACCEPT,
    USER_AGENT,
    fetch_text as http_fetch_text,
)
from app.collectors.raw import CollectResult, RawArticle
from app.config.sources import NewsSource
from app.pipelines.normalize import news_item_from_raw
from app.pipelines.urls import canonicalize_url

ANTHROPIC_BASE = "https://www.anthropic.com"
DEEPSEEK_BASE = "https://api-docs.deepseek.com"
KIMI_BASE = "https://www.kimi.com"
COHERE_BASE = "https://cohere.com"
CURSOR_BASE = "https://cursor.com"
BYTEDANCE_SEED_BASE = "https://seed.bytedance.com"
HUNYUAN_BASE = "https://hunyuan.tencent.com"
ZHIPU_BASE = "https://www.zhipuai.cn"
MINIMAX_BASE = "https://www.minimax.cn"

# Cohere prints the publish date in an "eyebrow" line above each card: a
# <p> whose whole text is the date. Anchoring on the element rather than on a
# class means a restyle does not move the date, and walking up from it to the
# nearest container that holds a /blog/ link keeps the card boundary honest.
COHERE_DATE_CLASS = "font-eyebrow"

# Cursor's listing has two shapes: dated directory rows and undated featured
# cards. The row shape is preferred because it carries the date; a featured card
# without a date is skipped rather than guessed at.
CURSOR_ROW_SELECTOR = "a.blog-directory__row"
CURSOR_CARD_SELECTOR = "a.card--media, a.card--feature"

ENGLISH_DATE_FORMATS = ("%b %d, %Y", "%B %d, %Y", "%b. %d, %Y")
ENGLISH_DATE_RE = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},\s*\d{4}\b"
)
DEEPSEEK_DATE_RE = re.compile(r"(\d{4}/\d{2}/\d{2})\s*$")
KIMI_ARTICLE_LIST = '\\"articleList\\"'
KIMI_ITEMS = '\\"items\\":'

COHERE_LINK_PREFIX = "/blog/"
CURSOR_LINK_PREFIX = "/blog/"
MINIMAX_LINK_PREFIX = "/blog/"
# Paths under /blog/ that are index pages rather than articles.
LISTING_PATH_SEGMENTS = ("/topic/", "/tag/", "/category/", "/author/", "/page/")

# ByteDance Seed renders its blog list on the server and hands the result to the
# client as a plain JSON object in the page. Reading that payload is steadier
# than the markup around it, which is a CSS-framework class soup.
SEED_ROUTER_DATA = "window._ROUTER_DATA = "
SEED_BLOG_ROUTE = "(locale$)/blog/page"
SEED_ARTICLE_PREFIX = "/blog/"

# 腾讯混元's blog is a client-rendered shell with no article markup in the HTML
# at all, so the listing is read from the public JSON its own site calls. The
# endpoint is POST-only and takes a small paging body.
HUNYUAN_LIST_PAYLOAD = {"pageNum": 1, "pageSize": 50}
HUNYUAN_ARTICLE_PREFIX = "/research/"
HUNYUAN_LANGUAGE = "zh"

# 智谱 publishes its news and research listing as a React Server Components
# flight payload, where each record is an escaped JSON object.
ZHIPU_FLIGHT_MARKER = '\\"newsItems\\":'
ZHIPU_NEWS_SEGMENT = "news"
ZHIPU_RESEARCH_SEGMENT = "research"

# MiniMax prints an unambiguous YYYY-MM-DD in each card's metadata line.
MINIMAX_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


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


def bytedance_seed_entries(html: str) -> list[tuple[str, str, datetime]]:
    """ByteDance Seed's blog list, read from the payload the page ships with.

    The listing is server-rendered into ``window._ROUTER_DATA`` rather than into
    markup, so the article list is read from that JSON: date, Chinese title and
    the slug that forms the article's own URL. A page that no longer carries the
    route is reported as changed instead of quietly yielding nothing.
    """
    marker = html.find(SEED_ROUTER_DATA)
    if marker < 0:
        raise PageStructureError("no router payload on the ByteDance Seed blog")
    end = html.find("</script>", marker)
    raw = html[marker + len(SEED_ROUTER_DATA) : end if end > 0 else None].strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PageStructureError(f"unreadable router payload on the Seed blog: {exc}") from exc

    page = (payload.get("loaderData") or {}).get(SEED_BLOG_ROUTE)
    if not isinstance(page, dict) or "article_list" not in page:
        raise PageStructureError("no article list in the ByteDance Seed payload")

    entries: list[tuple[str, str, datetime]] = []
    for item in page.get("article_list") or []:
        if not isinstance(item, dict):
            continue
        meta = item.get("ArticleMeta") or {}
        # PublishDate is epoch milliseconds at UTC midnight of the local day.
        raw_date = meta.get("PublishDate")
        if not isinstance(raw_date, (int, float)):
            continue
        published = datetime.fromtimestamp(raw_date / 1000, tz=timezone.utc)
        # The Chinese record carries the title and abstract the digest wants; the
        # English one is the fallback for a post that only exists in English.
        content = item.get("ArticleSubContentZh") or item.get("ArticleSubContentEn") or {}
        title = str(content.get("Title") or "").strip()
        slug = str(content.get("TitleKey") or "").strip()
        if not title or not slug:
            continue
        entries.append(
            (urljoin(BYTEDANCE_SEED_BASE, f"/blog/{slug}"), title, published)
        )
    return entries


def tencent_hunyuan_entries(payload: str) -> list[tuple[str, str, datetime]]:
    """Tencent Hunyuan's blog list, from the public JSON its site reads.

    The listing endpoint returns ``{"code":0,...,"data":{"list":[...]}}`` where
    each record carries a Chinese title and ``publishedAt`` as epoch seconds.
    The article's URL is built from ``customUrl``, falling back to the numeric id
    for the few posts that have no slug.
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise PageStructureError(f"unreadable Hunyuan listing JSON: {exc}") from exc

    if not isinstance(data, dict) or data.get("code") not in (0, None):
        raise PageStructureError(f"Hunyuan listing returned an error: {data.get('msg')!r}")
    records = ((data.get("data") or {}).get("list")) if isinstance(data.get("data"), dict) else None
    if not isinstance(records, list):
        raise PageStructureError("no article list in the Hunyuan listing payload")

    entries: list[tuple[str, str, datetime]] = []
    for item in records:
        if not isinstance(item, dict):
            continue
        # displayPublishTime is the day the post is dated; publishedAt is when it
        # went live and is used only when the display date is missing.
        raw_date = item.get("displayPublishTime") or item.get("publishedAt") or item.get("createdAt")
        if not isinstance(raw_date, (int, float)):
            continue
        published = datetime.fromtimestamp(raw_date, tz=timezone.utc)
        title = str(item.get("title") or "").strip()
        slug = str(item.get("customUrl") or item.get("id") or "").strip()
        if not title or not slug:
            continue
        entries.append(
            (urljoin(HUNYUAN_BASE, f"{HUNYUAN_ARTICLE_PREFIX}{slug}"), title, published)
        )
    return entries


def zhipu_entries(html: str) -> list[tuple[str, str, datetime]]:
    """智谱's news and research listing, read from its flight payload.

    The page is a React Server Components response, so the records arrive as
    escaped JSON inside ``self.__next_f.push`` calls. Each record has a Chinese
    title, a ``createAt`` timestamp and a ``category`` that decides which section
    its URL belongs to. Both categories are collected: the research posts are
    model releases and the news posts are corporate announcements, and a digest
    that only took one of them would miss half of what the vendor published.
    """
    marker = html.find(ZHIPU_FLIGHT_MARKER)
    if marker < 0:
        raise PageStructureError("no news payload on the Zhipu listing page")

    # The payload is escaped, so decode before scanning for the array brackets;
    # otherwise escaped quotes would be read as string delimiters.
    decoded = _unescape_payload(html[marker:])
    raw_array = _extract_json_array(decoded, decoded.find("["))
    if raw_array is None:
        raise PageStructureError("unterminated news array in the Zhipu payload")
    try:
        items = json.loads(raw_array)
    except json.JSONDecodeError as exc:
        raise PageStructureError(f"unreadable news array in the Zhipu payload: {exc}") from exc
    if not isinstance(items, list):
        raise PageStructureError("Zhipu news payload is not a list")

    entries: list[tuple[str, str, datetime]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        # English-only records carry a null Chinese title; the English one is not
        # used, because a Chinese digest showing an untranslated headline is
        # worse than not carrying the post.
        title = str(item.get("title_zh") or "").strip()
        raw_date = str(item.get("createAt") or "").strip()
        identifier = str(item.get("id") or "").strip()
        if not title or not identifier:
            continue
        try:
            published = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        except ValueError:
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        segment = (
            ZHIPU_RESEARCH_SEGMENT
            if str(item.get("category") or "") == "blog"
            else ZHIPU_NEWS_SEGMENT
        )
        entries.append(
            (urljoin(ZHIPU_BASE, f"/zh/{segment}/{identifier}"), title, published.astimezone(timezone.utc))
        )
    return entries


def minimax_entries(html: str) -> list[tuple[str, str, datetime]]:
    """MiniMax's blog listing: dated cards with a heading and a standfirst.

    The listing is server-rendered, and each card is one ``/blog/`` anchor that
    prints its metadata line (category, then ``YYYY-MM-DD``) above an ``<h3>``
    headline. Anchoring on the anchor and reading its own text keeps the card
    boundary honest even as the surrounding grid changes.
    """
    soup = BeautifulSoup(html, "html.parser")
    anchors = [
        anchor
        for anchor in soup.find_all("a", href=True)
        if _is_article_path(str(anchor["href"]), MINIMAX_LINK_PREFIX)
    ]
    if not anchors:
        raise PageStructureError("no /blog/ links on the MiniMax blog")

    entries: list[tuple[str, str, datetime]] = []
    seen: set[str] = set()
    for anchor in anchors:
        href = str(anchor["href"]).strip()
        date_match = MINIMAX_DATE_RE.search(anchor.get_text(" ", strip=True))
        if date_match is None:
            continue
        try:
            published = datetime.strptime(date_match.group(1), "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            continue
        heading = anchor.find(["h1", "h2", "h3", "h4"])
        title = _clean_card_text(heading.get_text(" ", strip=True) if heading else "")
        if not title:
            continue
        url = urljoin(MINIMAX_BASE, href)
        canonical = canonicalize_url(url)
        if canonical in seen:
            continue
        seen.add(canonical)
        entries.append((url, title, published))
    return entries


def _is_article_path(href: str, prefix: str) -> bool:
    """Whether a listing link points at an article rather than an index page."""
    if not href.startswith(prefix):
        return False
    return not any(segment in href for segment in LISTING_PATH_SEGMENTS)


def _card_from_date_element(
    date_el: Tag, *, prefix: str, base: str
) -> tuple[str, str, datetime] | None:
    """Walk up from a date element to the smallest container holding the card.

    The card boundary is defined by structure ("this element contains both the
    date and exactly one article link") rather than by a hashed CSS class, so a
    site restyle that keeps its layout keeps working.
    """
    published = parse_english_date(date_el.get_text(" ", strip=True))
    if published is None:
        return None
    node: Tag | None = date_el
    for _ in range(8):
        node = node.parent if node is not None else None
        if node is None or node.name in {"body", "html"}:
            return None
        links = [
            anchor
            for anchor in node.find_all("a", href=True)
            if _is_article_path(str(anchor["href"]), prefix)
        ]
        if not links:
            continue
        # A card is often two anchors: one around the cover image, one around the
        # headline. The one carrying the text is the headline, so the longest
        # anchor wins rather than whichever happens to come first in the markup.
        anchor = max(links, key=lambda item: len(item.get_text(" ", strip=True)))
        href = str(anchor["href"])
        title = _card_title(anchor, node)
        if not title:
            return None
        return (urljoin(base, href), title, published)
    return None


def _card_title(anchor: Tag, container: Tag) -> str:
    """The card's headline, taken from the link's own text block.

    The headline is the first heading or paragraph inside the anchor, because the
    cards print title first and standfirst second. Anything from a date onwards is
    cut, since some cards put the date and reading time inside the same link. The
    image's ``alt`` is the last resort: on Cohere it describes the picture rather
    than the article, so it must never win over real text.
    """
    for element in anchor.find_all(["h1", "h2", "h3", "h4", "p"]):
        title = _clean_card_text(element.get_text(" ", strip=True))
        if title:
            return title
    title = _clean_card_text(anchor.get_text(" ", strip=True))
    if title:
        return title
    for image in [*anchor.find_all("img"), *container.find_all("img")]:
        alt = _clean_card_text(image.get("alt"))
        if alt:
            return alt
    return ""


def _clean_card_text(value: object) -> str:
    """Trim a card's text down to a headline.

    Cards mix the headline with the publish date, the reading time and sometimes
    the standfirst. The date starts the metadata, so everything from it onwards is
    dropped; a trailing "5 min read" is dropped too. A headline that legitimately
    contains a date would be truncated, which is why this is only used on listing
    labels and never on an article's own title.
    """
    text = " ".join(str(value or "").split())
    match = ENGLISH_DATE_RE.search(text)
    if match is not None:
        text = text[: match.start()]
    text = re.sub(r"\s*\d+\s*(?:min|minute|minutes)\s+read\s*$", "", text, flags=re.IGNORECASE)
    return text.strip(" ·|·—-–\t")


def cohere_entries(html: str) -> list[tuple[str, str, datetime]]:
    """Cohere's blog: each card prints its date in an eyebrow line."""
    soup = BeautifulSoup(html, "html.parser")
    if not _listing_anchors(soup, COHERE_LINK_PREFIX):
        # No /blog/ links at all means the listing itself is gone, which is a
        # markup change rather than a quiet week.
        raise PageStructureError("no /blog/ links on the Cohere blog")
    date_elements = [
        element
        for element in soup.find_all(["p", "span", "time"])
        if COHERE_DATE_CLASS in (element.get("class") or [])
        or element.name == "time"
    ]

    entries: list[tuple[str, str, datetime]] = []
    seen: set[str] = set()
    for element in date_elements:
        card = _card_from_date_element(element, prefix=COHERE_LINK_PREFIX, base=COHERE_BASE)
        if card is None:
            continue
        url, title, published = card
        if url in seen:
            continue
        seen.add(url)
        entries.append((url, title, published))
    return entries


def cursor_entries(html: str) -> list[tuple[str, str, datetime]]:
    """Cursor's blog: dated directory rows, newest mixed with older cards."""
    soup = BeautifulSoup(html, "html.parser")
    if not _listing_anchors(soup, CURSOR_LINK_PREFIX):
        raise PageStructureError("no /blog/ links on the Cursor blog")
    rows = soup.select(CURSOR_ROW_SELECTOR)

    entries: list[tuple[str, str, datetime]] = []
    seen: set[str] = set()
    for row in rows:
        href = str(row.get("href") or "").strip()
        if not _is_article_path(href, CURSOR_LINK_PREFIX):
            continue
        time_el = row.find("time")
        if time_el is None:
            continue
        published = _iso_datetime(str(time_el.get("datetime") or "")) or parse_english_date(
            time_el.get_text(" ", strip=True)
        )
        if published is None:
            continue
        title = _cursor_row_title(row, href)
        if not title:
            continue
        url = urljoin(CURSOR_BASE, href)
        canonical = canonicalize_url(url)
        if canonical in seen:
            continue
        seen.add(canonical)
        entries.append((url, title, published))
    return entries


def _listing_anchors(soup: BeautifulSoup, prefix: str) -> list[Tag]:
    """Article links on a listing page, used to tell "empty" from "changed"."""
    return [
        anchor
        for anchor in soup.find_all("a", href=True)
        if _is_article_path(str(anchor["href"]), prefix)
    ]


def _cursor_row_title(row: Tag, href: str) -> str:
    """A Cursor directory row's headline.

    The row is a grid: a date column, a headline column, then author and reading
    time. The headline is the first non-empty ``<p>`` that is not the date, is
    not a duration, and is not one of the author names, which is what the first
    two fields after the date always are.
    """
    for paragraph in row.select("p"):
        text = " ".join(paragraph.get_text(" ", strip=True).split())
        if not text or ENGLISH_DATE_RE.fullmatch(text):
            continue
        if re.fullmatch(r"\d+\s*(m|min|minute|minutes|h|hr|hour|hours|d|day|days)", text):
            continue
        return text
    # Older rows carry the headline in a heading instead of a paragraph.
    heading = row.find(["h1", "h2", "h3", "h4"])
    if heading is not None:
        text = " ".join(heading.get_text(" ", strip=True).split())
        if text:
            return text
    return href.rsplit("/", 1)[-1].replace("-", " ").strip()


def _iso_datetime(raw: str) -> datetime | None:
    """An ISO-8601 timestamp from a ``<time datetime=...>`` attribute."""
    text = raw.strip()
    if not text:
        return None
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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
        elif source.id == "cohere":
            entries = cohere_entries(index_html)
        elif source.id == "cursor":
            entries = cursor_entries(index_html)
        elif source.id == "bytedance-seed":
            entries = bytedance_seed_entries(index_html)
        elif source.id == "tencent-hunyuan":
            entries = tencent_hunyuan_entries(page_html or index_html)
        elif source.id == "zhipu-glm":
            entries = zhipu_entries(index_html)
        elif source.id == "minimax":
            entries = minimax_entries(index_html)
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


def fetch_hunyuan_listing(url: str, timeout: float = DEFAULT_TIMEOUT) -> str:
    """Read Hunyuan's blog listing.

    This is the one source that is not a document: its listing endpoint is
    POST-only and answers with JSON, so it cannot go through ``fetch_text``.
    Kept as its own function so a test can serve it a fixture exactly the way
    ``fetch_html`` is stubbed for the page-based sources.
    """
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "accept-language": HUNYUAN_LANGUAGE,
    }
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
        response = client.post(url, json=HUNYUAN_LIST_PAYLOAD)
        response.raise_for_status()
        return response.text


def collect_html_source(
    source: NewsSource,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    fetch_text=None,
    fetch_listing=None,
) -> CollectResult:
    # Hunyuan is the one source whose listing is a JSON API rather than a page,
    # so it reads through its own fetcher. Everything else takes the shared one.
    if source.id == "tencent-hunyuan":
        fetch = fetch_listing or fetch_text or fetch_hunyuan_listing
    else:
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
