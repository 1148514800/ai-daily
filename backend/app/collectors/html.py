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
from urllib.parse import quote, urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

import httpx

from app.collectors.http import (
    DEFAULT_TIMEOUT,
    HTML_ACCEPT,
    USER_AGENT,
    fetch_text as http_fetch_text,
)
from app.collectors.raw import CollectResult, RawArticle
from app.config.sources import NewsSource
from app.pipelines.ai_filter import is_ai_related
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
TENCENT_CLOUD_BASE = "https://cloud.tencent.com"
WORKBUDDY_BASE = "https://www.codebuddy.cn"
META_AI_BASE = "https://ai.meta.com"
ALIBABA_MODEL_STUDIO_BASE = "https://help.aliyun.com"

# 阿里云's catalogue identifies a model's family in its id prefix; the brand is
# used to make the headline readable in Chinese, and an unknown prefix simply
# leaves the id alone. Matched as a prefix because the family carries a version
# in the id itself (``qwen3.8-max-0902``), so an exact-id lookup would miss
# most rows.
ALIBABA_MODEL_BRANDS = (
    ("qwen", "通义千问"),
    ("wan", "通义万相"),
    ("happyoyster", "HappyOyster"),
)

# Anthropic publishes on several paths from one newsroom page. Restricting the
# extractor to ``/news/`` is what hid the institute essay that started this
# phase, so every path the newsroom actually links to is accepted. The list is
# explicit rather than "any same-host link" so navigation, topic and author
# pages cannot slip in as articles.
ANTHROPIC_ARTICLE_PREFIXES = ("/news/", "/research/", "/institute/", "/engineering/")
# Paths under those prefixes that are index pages rather than articles.
ANTHROPIC_INDEX_SEGMENTS = ("/research/team/",)

# Anthropic's research index dates its cards the same way its newsroom does; the
# engineering blog prints the date in a div instead of a <time>, and its
# featured card carries no date at all.
ANTHROPIC_ENGINEERING_PREFIX = "/engineering/"
ANTHROPIC_RESEARCH_PREFIX = "/research/"

# Meta's AI blog ships hashed CSS-module classes, so cards are found by
# structure: a date element, and the nearest ancestor holding one article link.
META_AI_ARTICLE_RE = re.compile(r"^(?:https://ai\.meta\.com)?/blog/[^/]+/?$")
META_AI_DATE_RE = re.compile(r"^[A-Z][a-z]+ \d{1,2}, \d{4}$")
# Card labels that are not headlines: the featured card tags itself "FEATURED"
# on an anchor that points at the same article as its headline.
META_AI_SKIP_LABELS = re.compile(r"(?i)^(featured|learn more|read more|watch|see more|read)$")

# Cursor's changelog is a list of <article> blocks, each with an ISO <time> and
# a heading whose anchor is the release's own permalink.
CURSOR_CHANGELOG_PREFIX = "/changelog/"

# Cohere's research index carries no <time>; the publish date is the tail of
# each paper's slug ("...-2026-09-10").
COHERE_PAPER_PREFIX = "/research/papers/"
COHERE_SLUG_DATE_RE = re.compile(r"-(\d{4}-\d{2}-\d{2})$")

# 腾讯云's announcement list: one dated row per notice.
TENCENT_CLOUD_ARTICLE_PREFIX = "/announce/detail/"
TENCENT_CLOUD_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})")

# 腾讯 WorkBuddy's changelog is one page whose releases are <h2> headings, each
# carrying its date in the heading text ("5.5.6 版本发布 🚀（2026-09-10）").
WORKBUDDY_HEADING_RE = re.compile(r"[（(](\d{4}-\d{2}-\d{2})[）)]\s*$")

# 阿里云百炼's model catalogue renders its releases as dated table rows:
# 模型类型 / 时间 / 模型 ID / 功能说明. Rows have neither an id nor an anchor, so
# the model id is what names and identifies one.
ALIBABA_MODEL_ROW_MIN_CELLS = 4
ALIBABA_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

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


def parse_iso_date(raw: str) -> datetime | None:
    """A plain ``YYYY-MM-DD`` publish date, read as UTC midnight.

    Several sources date a release by its day alone, with no clock time and no
    offset. Reading that as UTC midnight is the same convention the other
    collectors use for a day-only date.
    """
    try:
        return datetime.strptime(str(raw).strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
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


def _anthropic_article_href(anchor: Tag) -> bool:
    """Whether an Anthropic card is an article rather than an index page.

    The newsroom links to ``/news/`` posts and to ``/institute/``, ``/research/``
    and ``/engineering/`` essays from the same page, and all of them are
    Anthropic's own announcements, so all of them are collected. A few posts sit
    at the top level instead (``/claude-fable-and-mythos-5-1``); those are
    recognised structurally, by the card carrying its own publish date, which
    navigation and section links never do.
    """
    text = str(anchor.get("href") or "").strip()
    if not text:
        return False
    # Some cards publish the absolute URL, so compare on the path only.
    path = urlsplit(text).path if text.startswith("http") else text
    if not path.startswith("/"):
        return False
    if any(segment in path for segment in ANTHROPIC_INDEX_SEGMENTS):
        return False
    if path.startswith(ANTHROPIC_ARTICLE_PREFIXES):
        return True
    return _anthropic_card_date(anchor) is not None


def _anthropic_title(anchor: Tag) -> str:
    """The headline of an Anthropic card, from its heading or title element."""
    heading = anchor.find(["h1", "h2", "h3", "h4", "h5", "h6"])
    if heading is not None:
        title = " ".join(heading.get_text(" ", strip=True).split())
        if title:
            return title
    title_el = anchor.select_one('[class*="title"]')
    if title_el is not None:
        return " ".join(title_el.get_text(" ", strip=True).split())
    return ""


def anthropic_entries(html: str) -> list[tuple[str, str, datetime]]:
    """Anthropic's newsroom: every article card, whatever its path.

    The page mixes two card shapes — a featured grid whose meta block holds a
    ``<time>``, and a publication list whose rows do the same — plus an
    engineering-style list that prints the date in a plain element. Anchoring on
    ``<time>`` when it exists and falling back to any element whose whole text
    is a date covers both without depending on hashed class names.
    """
    soup = BeautifulSoup(html, "html.parser")
    anchors = [
        anchor
        for anchor in soup.find_all("a", href=True)
        if _anthropic_article_href(anchor)
    ]
    if not anchors:
        raise PageStructureError("no article links on the Anthropic newsroom")

    entries: list[tuple[str, str, datetime]] = []
    seen: set[str] = set()
    for anchor in anchors:
        published = _anthropic_card_date(anchor)
        if published is None:
            continue
        title = _anthropic_title(anchor)
        if not title:
            continue
        url = urljoin(ANTHROPIC_BASE, str(anchor["href"]))
        canonical = canonicalize_url(url)
        if canonical in seen:
            continue
        seen.add(canonical)
        entries.append((url, title, published))
    return entries


def _anthropic_card_date(anchor: Tag) -> datetime | None:
    """The publish date of one Anthropic card, or None when it has none."""
    time_el = anchor.find("time")
    if time_el is not None:
        published = parse_english_date(time_el.get_text(" ", strip=True))
        if published is not None:
            return published
    # The engineering list prints the date in a div of its own; the whole
    # element text being a date is what identifies it, which a restyle cannot
    # silently break into a different meaning.
    for element in anchor.find_all(["time", "div", "span", "p"]):
        text = " ".join(element.get_text(" ", strip=True).split())
        if not text or not ENGLISH_DATE_RE.fullmatch(text):
            continue
        published = parse_english_date(text)
        if published is not None:
            return published
    return None


def anthropic_engineering_entries(html: str) -> list[tuple[str, str, datetime]]:
    """Anthropic's engineering blog: dated article cards, one featured undated.

    The featured card carries no date at all, so it is skipped rather than
    guessed at — the same rule the other listing extractors use.
    """
    soup = BeautifulSoup(html, "html.parser")
    anchors = [
        anchor
        for anchor in soup.select(f'a[href^="{ANTHROPIC_ENGINEERING_PREFIX}"]')
        if _is_article_path(str(anchor.get("href") or ""), ANTHROPIC_ENGINEERING_PREFIX)
    ]
    if not anchors:
        raise PageStructureError("no /engineering/ links on the Anthropic blog")

    entries: list[tuple[str, str, datetime]] = []
    seen: set[str] = set()
    for anchor in anchors:
        published = _anthropic_card_date(anchor)
        if published is None:
            continue
        title = _anthropic_title(anchor)
        if not title:
            continue
        url = urljoin(ANTHROPIC_BASE, str(anchor["href"]))
        canonical = canonicalize_url(url)
        if canonical in seen:
            continue
        seen.add(canonical)
        entries.append((url, title, published))
    return entries


def anthropic_research_entries(html: str) -> list[tuple[str, str, datetime]]:
    """Anthropic's research index, without its team pages."""
    soup = BeautifulSoup(html, "html.parser")
    anchors = [
        anchor
        for anchor in soup.select(f'a[href^="{ANTHROPIC_RESEARCH_PREFIX}"]')
        if _is_article_path(str(anchor.get("href") or ""), ANTHROPIC_RESEARCH_PREFIX)
    ]
    if not anchors:
        raise PageStructureError("no /research/ links on the Anthropic research index")

    entries: list[tuple[str, str, datetime]] = []
    seen: set[str] = set()
    for anchor in anchors:
        published = _anthropic_card_date(anchor)
        if published is None:
            continue
        title = _anthropic_title(anchor)
        if not title:
            continue
        url = urljoin(ANTHROPIC_BASE, str(anchor["href"]))
        canonical = canonicalize_url(url)
        if canonical in seen:
            continue
        seen.add(canonical)
        entries.append((url, title, published))
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


def cursor_changelog_entries(html: str) -> list[tuple[str, str, datetime]]:
    """Cursor's changelog: one ``<article>`` per release, dated by its ``<time>``.

    Features often ship here and nowhere else, so this channel exists to make
    them reachable. Each release links to its own permalink, so an entry is a
    real page rather than an anchor on a shared list.
    """
    soup = BeautifulSoup(html, "html.parser")
    articles = soup.find_all("article")
    if not articles:
        raise PageStructureError("no articles on the Cursor changelog")

    entries: list[tuple[str, str, datetime]] = []
    seen: set[str] = set()
    for article in articles:
        time_el = article.find("time")
        if time_el is None:
            continue
        published = _iso_datetime(str(time_el.get("datetime") or ""))
        if published is None:
            published = parse_english_date(time_el.get_text(" ", strip=True))
        if published is None:
            continue
        anchors = [
            candidate
            for candidate in article.find_all("a", href=True)
            if _is_article_path(str(candidate["href"]), CURSOR_CHANGELOG_PREFIX)
        ]
        if not anchors:
            continue
        # The release's own heading carries the title; the same href also
        # appears on an anchor that wraps only the date, so the date must not be
        # taken for a headline. Longest text wins, which prefers the heading.
        titled = [a for a in anchors if not ENGLISH_DATE_RE.fullmatch(_element_text(a))]
        anchor = max(titled or anchors, key=lambda a: len(_element_text(a)))
        title = _element_text(anchor)
        if not title or ENGLISH_DATE_RE.fullmatch(title):
            title = (
                str(anchor["href"]).rstrip("/").rsplit("/", 1)[-1].replace("-", " ").strip()
            )
        if not title:
            continue
        url = urljoin(CURSOR_BASE, str(anchor["href"]))
        canonical = canonicalize_url(url)
        if canonical in seen:
            continue
        seen.add(canonical)
        entries.append((url, title, published))
    return entries


def cohere_research_entries(html: str) -> list[tuple[str, str, datetime]]:
    """Cohere's research index: each paper's date ends its own slug.

    The cards carry no ``<time>`` (the date is printed in prose), but the slug
    is machine-stable: ``...-2026-09-10``. Reading the date from the permalink
    rather than from the label means a restyle cannot move it.
    """
    soup = BeautifulSoup(html, "html.parser")
    anchors = soup.select(f'a[href^="{COHERE_PAPER_PREFIX}"]')
    if not anchors:
        raise PageStructureError("no /research/papers/ links on the Cohere research page")

    entries: list[tuple[str, str, datetime]] = []
    seen: set[str] = set()
    for anchor in anchors:
        href = str(anchor.get("href") or "").strip()
        match = COHERE_SLUG_DATE_RE.search(href)
        if match is None:
            continue
        published = parse_iso_date(match.group(1))
        if published is None:
            continue
        title = " ".join(anchor.get_text(" ", strip=True).split())
        if not title:
            continue
        url = urljoin(COHERE_BASE, href)
        canonical = canonicalize_url(url)
        if canonical in seen:
            continue
        seen.add(canonical)
        entries.append((url, title, published))
    return entries


def tencent_cloud_entries(html: str) -> list[tuple[str, str, datetime]]:
    """腾讯云's announcement list: one dated row per notice.

    The list is a wide operations feed, so it is filtered by AI relevance
    afterwards; rows keep their title, their own ``/announce/detail/`` link and
    the timestamp printed beside them.
    """
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("div.msg-list-item")
    if not rows:
        raise PageStructureError("no announcement rows on the Tencent Cloud list")

    entries: list[tuple[str, str, datetime]] = []
    seen: set[str] = set()
    for row in rows:
        anchor = row.find("a", href=True)
        if anchor is None:
            continue
        href = str(anchor["href"]).strip()
        if not href.startswith(TENCENT_CLOUD_ARTICLE_PREFIX):
            continue
        title = " ".join(anchor.get_text(" ", strip=True).split())
        if not title:
            continue
        published = _tencent_cloud_date(row)
        if published is None:
            continue
        url = urljoin(TENCENT_CLOUD_BASE, href)
        canonical = canonicalize_url(url)
        if canonical in seen:
            continue
        seen.add(canonical)
        entries.append((url, title, published))
    return entries


def _tencent_cloud_date(row: Tag) -> datetime | None:
    """The ``YYYY-MM-DD HH:MM:SS`` an announcement row prints beside its title."""
    for element in row.find_all(["span", "div", "p", "time"]):
        text = " ".join(element.get_text(" ", strip=True).split())
        match = TENCENT_CLOUD_DATE_RE.fullmatch(text)
        if match is None:
            continue
        try:
            moment = datetime.strptime(f"{match.group(1)} {match.group(2)}", "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        return moment.replace(tzinfo=timezone.utc)
    return None


def tencent_workbuddy_entries(html: str) -> list[tuple[str, str, datetime]]:
    """腾讯 WorkBuddy's changelog: ``<h2>`` release headings carrying their date.

    Every release lives on one page and has no permalink of its own, so the
    entry's URL is the changelog plus the heading's fragment. The fragment is
    part of the URL on purpose: it is what makes two releases two entries
    instead of one, and it lands the reader on the right section.
    """
    soup = BeautifulSoup(html, "html.parser")
    headings = soup.find_all(["h2", "h3"])
    if not headings:
        raise PageStructureError("no release headings on the WorkBuddy changelog")

    entries: list[tuple[str, str, datetime]] = []
    seen: set[str] = set()
    for heading in headings:
        text = _clean_heading(heading.get_text(" ", strip=True))
        match = WORKBUDDY_HEADING_RE.search(text)
        if match is None:
            continue
        published = parse_iso_date(match.group(1))
        if published is None:
            continue
        title = text[: match.start()].strip(" 　·-—–")
        if not title:
            continue
        # A release has no permalink of its own, so the version becomes a query
        # value. A fragment would scroll to the right section but is stripped
        # when a URL is canonicalized, which would collapse all seventy
        # releases into one entry; a query value is kept and is still a URL the
        # changelog answers.
        version = title.split()[0] if title.split() else ""
        url = f"{WORKBUDDY_BASE}/docs/workbuddy/Changelog"
        if version:
            url = f"{url}?release={quote(version, safe='')}"
        canonical = canonicalize_url(url)
        if canonical in seen:
            continue
        seen.add(canonical)
        entries.append((url, title, published))
    return entries


def _element_text(value: object) -> str:
    """An element's text as one whitespace-collapsed line."""
    return " ".join(str(value.get_text(" ", strip=True) if isinstance(value, Tag) else value or "").split())


def _clean_heading(value: object) -> str:
    """A heading's text with its anchors and zero-width padding removed."""
    text = " ".join(str(value or "").replace("\u200b", " ").split())
    return text.strip()


def alibaba_model_entries(html: str) -> list[tuple[str, str, datetime]]:
    """阿里云百炼's newly released models: one dated row per model.

    The catalogue is a set of tables whose rows are 模型类型 / 时间 / 模型 ID /
    功能说明. The model id is the row's identity, so the entry's URL carries it
    as a query value: the rows have no anchor of their own, and without that the
    whole table would collapse to one URL and one entry.
    """
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    if not tables:
        raise PageStructureError("no tables on the Alibaba Model Studio catalogue")

    entries: list[tuple[str, str, datetime]] = []
    seen: set[str] = set()
    for table in tables:
        for row in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
            if len(cells) < ALIBABA_MODEL_ROW_MIN_CELLS:
                continue
            if not ALIBABA_DATE_RE.match(cells[1]):
                continue
            published = parse_iso_date(cells[1])
            if published is None:
                continue
            model_id = cells[2].strip()
            if not model_id:
                continue
            title = _alibaba_row_title(cells)
            # The fourth column describes what the model does. It is carried as
            # the summary because this page is a repeated catalogue that body
            # extraction rejects, so this is the only text the digest can use.
            summary = " ".join(cells[3].split())
            url = (
                f"{ALIBABA_MODEL_STUDIO_BASE}/zh/model-studio/newly-released-models"
                f"?model={quote(model_id, safe='')}"
            )
            canonical = canonicalize_url(url)
            if canonical in seen:
                continue
            seen.add(canonical)
            entries.append((url, title, published, summary))
    return entries


def _alibaba_row_title(cells: list[str]) -> str:
    """A catalogue row's headline: the model id and what it is for."""
    model_id = cells[2].strip()
    model_type = cells[0].strip()
    lowered = model_id.lower()
    brand = next(
        (label for prefix, label in ALIBABA_MODEL_BRANDS if lowered.startswith(prefix)),
        "",
    )
    name = f"{brand} {model_id}".strip() if brand else model_id
    if model_type and model_type != model_id:
        return f"{name}（{model_type}）"
    return name


def meta_ai_entries(html: str) -> list[tuple[str, str, datetime]]:
    """Meta's AI blog: dated cards whose class names are hashed and unstable.

    The markup is a CSS-module soup (``_amdj``, ``_8xkp``), so the card is
    defined structurally instead: an element whose whole text is a date, and the
    nearest ancestor holding exactly one blog article link. A restyle that keeps
    the layout keeps working; one that removes the date stops the source rather
    than silently dating an article wrongly.
    """
    soup = BeautifulSoup(html, "html.parser")
    if not soup.find("a", href=True):
        raise PageStructureError("no links at all on the Meta AI blog")
    # A card is found from its date, exactly as Cohere's is: walk up to the
    # nearest ancestor that links to one article and no other. Grouping anchors
    # by URL instead would span the whole page, because a "Learn More" control
    # in one card and a headline in another share an ancestor with many links.
    date_elements = [
        element
        for element in soup.find_all(["p", "span", "div", "time"])
        if META_AI_DATE_RE.match(_element_text(element))
    ]

    entries: list[tuple[str, str, datetime]] = []
    seen: set[str] = set()
    for element in date_elements:
        published = parse_english_date(_element_text(element))
        if published is None:
            continue
        card = _meta_card(element)
        if card is None:
            continue
        href, title = card
        url = urljoin(META_AI_BASE, href)
        canonical = canonicalize_url(url)
        if canonical in seen:
            continue
        seen.add(canonical)
        entries.append((url, title, published))
    return entries


def _meta_is_article(anchor: Tag) -> bool:
    """Whether a link on Meta's blog points at an article rather than a listing."""
    href = str(anchor.get("href") or "").strip()
    if not href:
        return False
    path = urlsplit(href).path if href.startswith("http") else href
    return bool(META_AI_ARTICLE_RE.match(path))


def _meta_card(date_el: Tag) -> tuple[str, str] | None:
    """The article one Meta AI card points at, plus its headline.

    The card boundary is "the nearest ancestor linking to exactly one article",
    which is a property of the layout rather than of the hashed class names.
    Every anchor in that container pointing at that article contributes a label,
    and the longest one that is not a control ("Learn More", "FEATURED") is the
    headline.
    """
    node: Tag | None = date_el
    for _ in range(8):
        node = node.parent if node is not None else None
        if node is None or node.name in {"body", "html"}:
            return None
        hrefs: dict[str, str] = {}
        for anchor in node.find_all("a", href=True):
            if not _meta_is_article(anchor):
                continue
            href = str(anchor["href"]).strip()
            hrefs.setdefault(canonicalize_url(urljoin(META_AI_BASE, href)), href)
        if len(hrefs) != 1:
            continue
        href = next(iter(hrefs.values()))
        labels = [
            _element_text(anchor)
            for anchor in node.find_all("a", href=True)
            if canonicalize_url(urljoin(META_AI_BASE, str(anchor["href"]).strip()))
            == canonicalize_url(urljoin(META_AI_BASE, href))
        ]
        usable = [label for label in labels if label and not META_AI_SKIP_LABELS.fullmatch(label)]
        # The list cards put the headline in a heading beside the link rather
        # than inside it, so a heading in the same card wins; the link's own
        # label is the fallback, and the slug the last resort.
        headings = [
            _element_text(heading)
            for heading in node.find_all(["h1", "h2", "h3", "h4"])
        ]
        headings = [text for text in headings if text]
        title = (
            max(headings, key=len)
            if headings
            else max(usable, key=len)
            if usable
            else href.rstrip("/").rsplit("/", 1)[-1].replace("-", " ")
        )
        return href, title.strip()
    return None


def _result_from_entries(
    source: NewsSource,
    entries: list[tuple[str, str, datetime]],
    *,
    fetched: int,
) -> CollectResult:
    """Turn extractor rows into the collector's result.

    A row is ``(url, title, published_at)``; a listing that also carries a short
    description may add a fourth element, which becomes the article's summary.
    That matters for a catalogue-shaped source (阿里云百炼's model list), whose
    own page is a huge repeated table that body extraction rejects: without the
    description the digest would see a bare model id and nothing else.
    """
    result = CollectResult(source_id=source.id, source_name=source.name)
    result.fetched = fetched
    seen: set[str] = set()
    for entry in entries:
        url, title, published = entry[0], entry[1], entry[2]
        summary = str(entry[3]).strip() if len(entry) > 3 and entry[3] else ""
        canonical = canonicalize_url(url)
        if canonical in seen:
            result.skipped += 1
            continue
        seen.add(canonical)
        # A wide official feed (Tencent Cloud's operational announcements, say)
        # is filtered here, before the entry can reach the window, dedupe or the
        # LLM. Counted as skipped rather than as an error: dropping the non-AI
        # part of a feed is the source working correctly. The RSS path applies
        # the same rule to the same flag.
        if source.requires_ai_filter and not is_ai_related(title, summary):
            result.skipped += 1
            continue
        raw = RawArticle(
            source_id=source.id,
            source=source.name,
            source_type=source.source_type,
            title=title,
            url=url,
            canonical_url=canonical,
            published_at=published,
            summary=summary,
        )
        result.valid.append(raw)
        result.news_items.append(news_item_from_raw(raw))
    return result


def parse_html_page(source: NewsSource, *, index_html: str, page_html: str | None = None) -> CollectResult:
    """Parse already fetched HTML for a source. Split out so tests stay offline."""
    try:
        if source.id == "anthropic":
            entries = anthropic_entries(index_html)
        elif source.id == "anthropic-research":
            entries = anthropic_research_entries(index_html)
        elif source.id == "anthropic-engineering":
            entries = anthropic_engineering_entries(index_html)
        elif source.id == "kimi":
            entries = kimi_entries(index_html)
        elif source.id == "deepseek":
            entries = deepseek_entries(page_html or index_html)
        elif source.id == "cohere":
            entries = cohere_entries(index_html)
        elif source.id == "cohere-research":
            entries = cohere_research_entries(index_html)
        elif source.id == "cursor":
            entries = cursor_entries(index_html)
        elif source.id == "cursor-changelog":
            entries = cursor_changelog_entries(index_html)
        elif source.id == "tencent-cloud-ai":
            entries = tencent_cloud_entries(index_html)
        elif source.id == "tencent-workbuddy":
            entries = tencent_workbuddy_entries(index_html)
        elif source.id == "alibaba-model-studio":
            entries = alibaba_model_entries(index_html)
        elif source.id == "meta-ai-blog":
            entries = meta_ai_entries(index_html)
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
