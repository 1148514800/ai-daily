"""Original article body extraction for the news pipeline.

The digest list shows a short Chinese summary; the detail view shows the article
as it was written. This module produces that second, original-language body.
There is one shared pipeline for every source instead of eleven parsers: sources
differ in *where* their listing lives, which the collectors already handle, not
in what an article body looks like.

Body sources, highest priority first:

1. the full body the feed itself carries (``content:encoded``, Atom ``content``,
   or a ``description`` long enough to be the whole article);
2. the article's own web page;
3. the feed's own description / summary, all that is left when the page cannot be
   read (paywall, 403, timeout, non-HTML).

The text is never translated, rewritten, or summarised here. It is stored in the
language it was published in; the Chinese ``title_cn`` / ``summary`` /
``why_it_matters`` fields are produced separately by the LLM, and the two never
overwrite each other.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag

from app.collectors.http import DEFAULT_TIMEOUT, FetchError, FetchResult, fetch_document
from app.collectors.raw import RawArticle
from app.config.env import BACKEND_ROOT

logger = logging.getLogger(__name__)

# How the body was obtained, stored with the row so a wrong body can be traced
# back to the method that produced it.
METHOD_RSS_FULL = "rss_full"
METHOD_WEB = "web"
METHOD_RSS_SUMMARY = "rss_summary"
METHOD_NONE = "none"

# Debug/stat labels, kept separate from the stored values so the log can say
# CACHE without losing the method the cached body came from.
LABEL_CACHE = "CACHE"
LABEL_FALLBACK = "FALLBACK"

MIN_BLOCK_CHARS = 2

WHITESPACE_RE = re.compile(r"[\s\u00a0\u200b]+")
PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n+")

KANA_RE = re.compile(r"[\u3040-\u30ff]")
HANGUL_RE = re.compile(r"[\uac00-\ud7af]")
CYRILLIC_RE = re.compile(r"[\u0400-\u04ff]")
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
LATIN_RE = re.compile(r"[A-Za-z]")

# Scripts counted for language detection. Below the threshold a stray kana or
# cyrillic character inside an English page must not change the answer.
SCRIPT_MIN_COUNT = 5

# Elements that never contain article prose.
DROP_TAGS = {
    "script",
    "style",
    "noscript",
    "template",
    "iframe",
    "svg",
    "canvas",
    "form",
    "input",
    "select",
    "textarea",
    "button",
    "nav",
    "aside",
    "footer",
    "dialog",
    "video",
    "audio",
    "source",
    "object",
    "embed",
}

# Containers that hold prose as one indivisible block.
ATOMIC_TAGS = {"p", "pre", "td", "th", "dd", "dt", "figcaption", "address"}

# Containers that hold further blocks and must be descended into.
BLOCK_TAGS = {
    "div",
    "section",
    "article",
    "main",
    "ul",
    "ol",
    "dl",
    "table",
    "thead",
    "tbody",
    "tr",
    "figure",
    "details",
    "summary",
    "header",
    "html",
    "body",
}

HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")

BOILERPLATE_ROLES = {"navigation", "banner", "contentinfo", "search", "menu", "menubar", "dialog"}

# Chrome that survives the tag filter because it is wrapped in a plain <div>.
# Matched against class and id only, never against text, so a sentence about
# cookies in the article is not mistaken for a cookie banner.
#
# Every token requires a separator or an end, so a class is only matched as a
# whole word. A plain substring match is not safe here: "nav" inside
# "navigation-with-keyboard" (a real DeepSeek <body> class) would decompose the
# entire document, and "ad" would match "header"/"shadow".
BOILERPLATE_PATTERNS = tuple(
    re.compile(rf"(?:^|[-_]){token}(?:$|[-_])")
    for token in (
        "ad",
        "ads",
        "advert",
        "adsbygoogle",
        "sponsor",
        "sponsored",
        "promo",
        "cookie",
        "cookies",
        "consent",
        "gdpr",
        "banner",
        "paywall",
        "newsletter",
        "subscribe",
        "signup",
        "social",
        "share",
        "sharing",
        "related",
        "recommend",
        "recommended",
        "readmore",
        "readnext",
        "popular",
        "sidebar",
        "nav",
        "navbar",
        "navigation",
        "menu",
        "breadcrumb",
        "breadcrumbs",
        "masthead",
        "header",
        "footer",
        "skip",
        "search",
        "modal",
        "popup",
        "overlay",
        "tooltip",
        "pagination",
        "pager",
        "tag",
        "tags",
        "byline",
    )
)

# Prose containers, most specific first. The first one that yields enough text
# wins, so a page with <article> never falls back to a whole-page <main>.
CONTENT_SELECTORS = (
    "[itemprop=articleBody]",
    "article",
    "main",
    "[role=main]",
    ".post-content",
    ".entry-content",
    ".article-content",
    ".article-body",
    ".post-body",
    ".markdown-body",
    ".article",
    ".post",
    "#content",
    ".content",
)


class ExtractionError(Exception):
    """One article could not be extracted. Never aborts the refresh."""


@dataclass(frozen=True)
class ExtractionSettings:
    """Tunables for body extraction, in one place instead of at call sites."""

    # A feed body at least this long is treated as the whole article, so the
    # page is never fetched. Shorter ones are summaries that need the page.
    rss_full_min_chars: int = 600
    # A page must yield at least this much text to replace the feed summary;
    # below it, the page almost certainly blocked us or served a stub.
    web_min_chars: int = 200
    # Safety valve against storing a whole page (a listing, a dump) as a body.
    max_chars: int = 40000
    # A single block longer than this is page chrome, not a paragraph. Generous
    # on purpose: a legitimately long paragraph must never be dropped, only a
    # wrapper that swallowed the whole page.
    max_block_chars: int = 10000
    timeout: float = DEFAULT_TIMEOUT
    cache_dir: Path | None = None

    @property
    def effective_cache_dir(self) -> Path | None:
        return self.cache_dir or default_cache_dir()


DEFAULT_SETTINGS = ExtractionSettings()


def default_cache_dir() -> Path:
    """Where extracted bodies are cached, keyed by canonical URL."""
    raw = (os.getenv("ARTICLE_CACHE_DIR") or "").strip()
    path = Path(raw) if raw else BACKEND_ROOT / ".cache" / "articles"
    if not path.is_absolute():
        path = BACKEND_ROOT / path
    return path


def load_extraction_settings() -> ExtractionSettings:
    return ExtractionSettings(cache_dir=default_cache_dir())


@dataclass(frozen=True)
class ArticleContent:
    """The cleaned original body of one article."""

    text: str
    language: str
    method: str
    error: str | None = None
    from_cache: bool = False

    @property
    def ok(self) -> bool:
        return bool(self.text)


def _clean_text(value: str) -> str:
    return WHITESPACE_RE.sub(" ", str(value or "")).strip()


def normalize_plain_text(text: str) -> str:
    """Normalise already-plain text into paragraphs separated by blank lines."""
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    blocks = [_clean_text(line) for line in raw.split("\n")]
    return "\n\n".join(block for block in blocks if block)


def _class_and_id(tag: Tag) -> str:
    attrs = tag.attrs or {}
    classes = attrs.get("class") or []
    if isinstance(classes, str):
        classes = [classes]
    parts = [str(item) for item in classes]
    identifier = attrs.get("id")
    if identifier:
        parts.append(str(identifier))
    return " ".join(parts).lower()


def _is_boilerplate(tag: Tag) -> bool:
    attrs = tag.attrs or {}
    name = (tag.name or "").lower()
    if name in ROOT_TAGS:
        return False
    if name in DROP_TAGS:
        return True
    role = str(attrs.get("role") or "").lower()
    if role in BOILERPLATE_ROLES:
        return True
    if str(attrs.get("aria-hidden") or "").lower() == "true":
        return True
    haystack = _class_and_id(tag)
    if not haystack:
        return False
    return any(pattern.search(haystack) for pattern in BOILERPLATE_PATTERNS)


STRUCTURAL_TAGS = BLOCK_TAGS | ATOMIC_TAGS | set(HEADING_TAGS) | {"li", "blockquote"}

# The document roots are never boilerplate, whatever class a framework puts on
# them: dropping one would throw the article away. DeepSeek, for example, labels
# its <body> "navigation-with-keyboard".
ROOT_TAGS = {"html", "body", "main", "article"}


def _has_block_child(tag: Tag) -> bool:
    """Whether ``tag`` wraps further blocks rather than a single run of text.

    Only the direct children are inspected. ``_walk`` descends one level at a
    time anyway, so a recursive check here would make the whole traversal
    quadratic on the large pages this module actually meets.
    """
    for child in tag.children:
        if isinstance(child, Tag) and (child.name or "").lower() in STRUCTURAL_TAGS:
            return True
    return False


def _append_block(blocks: list[str], text: str, *, settings: ExtractionSettings) -> None:
    cleaned = _clean_text(text)
    if len(cleaned) < MIN_BLOCK_CHARS or len(cleaned) > settings.max_block_chars:
        return
    if blocks and blocks[-1] == cleaned:
        return
    blocks.append(cleaned)


def _walk(node: Tag, blocks: list[str], settings: ExtractionSettings) -> None:
    """Collect the readable blocks of ``node`` in document order.

    Sibling text is gathered into a single paragraph, so a wrapper that
    interleaves its own text with nested blocks still keeps its own sentences.
    """
    pending: list[str] = []

    def flush() -> None:
        if pending:
            _append_block(blocks, " ".join(pending), settings=settings)
            pending.clear()

    for child in node.children:
        if isinstance(child, NavigableString):
            text = _clean_text(str(child))
            if text:
                pending.append(text)
            continue
        if not isinstance(child, Tag):
            continue
        if _is_boilerplate(child):
            continue
        name = (child.name or "").lower()
        flush()
        if name in HEADING_TAGS:
            text = _clean_text(child.get_text(" ", strip=True))
            if text:
                blocks.append(f"{'#' * int(name[1])} {text}")
            continue
        if name == "li":
            _append_block(blocks, f"- {child.get_text(' ', strip=True)}", settings=settings)
            continue
        if name == "blockquote":
            _append_block(blocks, f"> {child.get_text(' ', strip=True)}", settings=settings)
            continue
        if name in ATOMIC_TAGS:
            _append_block(blocks, child.get_text(" ", strip=True), settings=settings)
            continue
        if name in BLOCK_TAGS or _has_block_child(child):
            _walk(child, blocks, settings)
            continue
        _append_block(blocks, child.get_text(" ", strip=True), settings=settings)
    flush()


def _drop_leading_title(blocks: list[str], title: str) -> list[str]:
    """Remove the page's own heading when it just repeats the feed title.

    The detail view already prints the original title, so a body starting with
    the same line would repeat it. Only the first block is considered, and only
    when the two are close in length, so a short feed title never eats a longer
    and genuinely different heading.
    """
    wanted = _clean_text(title).lower()
    if not wanted or not blocks:
        return blocks
    head = blocks[0].lstrip("# ").strip().lower()
    if not head:
        return blocks
    if head == wanted:
        return blocks[1:]
    shorter, longer = sorted((head, wanted), key=len)
    if len(shorter) >= 20 and len(shorter) >= len(longer) * 0.6 and longer.startswith(shorter):
        return blocks[1:]
    return blocks


def _best_container(soup: BeautifulSoup) -> Tag:
    """The element most likely to hold the article body.

    Every selector is considered and the largest surviving candidate wins,
    with the selector order only breaking ties. Stopping at the first selector
    that matches anything is not good enough: a page whose real body is in
    ``<main>`` often also contains a tiny ``<article>`` card for a related post,
    and picking that would return a few words instead of the article.

    Boilerplate has already been removed by the caller, so the counts here are
    of the text that would actually be kept.
    """
    candidates: list[tuple[int, Tag]] = []
    for priority, selector in enumerate(CONTENT_SELECTORS):
        for node in soup.select(selector):
            if _is_boilerplate(node):
                continue
            candidates.append((priority, node))
    if not candidates:
        return soup.body or soup
    # Longest text first; on a tie the earlier (more specific) selector wins.
    return max(candidates, key=lambda entry: (len(entry[1].get_text(" ", strip=True)), -entry[0]))[1]


def clean_html(html: str, *, title: str = "", settings: ExtractionSettings = DEFAULT_SETTINGS) -> str:
    """Turn an article page (or feed body) into readable original text.

    Structure is kept where it is meaningful: headings keep their level, lists
    and quotes keep a marker, everything else becomes a paragraph. Navigation,
    cookie banners, share buttons, related links, ads, and scripts are dropped
    before any text is read, and the result is never translated.
    """
    raw = str(html or "")
    if not raw.strip():
        return ""
    if "<" not in raw:
        return normalize_plain_text(raw)

    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup.find_all(True):
        if _is_boilerplate(tag):
            tag.decompose()

    container = _best_container(soup)
    blocks: list[str] = []
    _walk(container, blocks, settings)
    blocks = _drop_leading_title(blocks, title)

    if blocks:
        text = "\n\n".join(blocks)
    else:
        # Nothing looked like a paragraph, which happens when a site wraps the
        # whole article in one unstyled container. The text is still the
        # article, so it is kept rather than reported as an empty body.
        text = normalize_plain_text(container.get_text(" ", strip=True))
    if len(text) > settings.max_chars:
        text = text[: settings.max_chars].rstrip()
    return text


def detect_language(text: str) -> str:
    """Best-effort script detection, enough to label the body honestly.

    Deliberately not a statistical language identifier: it only needs to tell
    English from Chinese so the detail view can say what language the body is in
    without ever translating it.
    """
    sample = str(text or "")[:4000]
    if not sample.strip():
        return ""
    kana = len(KANA_RE.findall(sample))
    hangul = len(HANGUL_RE.findall(sample))
    cyrillic = len(CYRILLIC_RE.findall(sample))
    cjk = len(CJK_RE.findall(sample))
    latin = len(LATIN_RE.findall(sample))

    if kana >= SCRIPT_MIN_COUNT:
        return "ja"
    if hangul >= SCRIPT_MIN_COUNT and hangul > latin:
        return "ko"
    if cyrillic >= SCRIPT_MIN_COUNT and cyrillic > latin:
        return "ru"
    if cjk >= SCRIPT_MIN_COUNT and cjk >= latin:
        return "zh"
    if latin:
        return "en"
    return "und"


def truncate_for_llm(text: str, limit: int) -> str:
    """The LLM input view of a body.

    The database keeps the whole body; only the prompt is trimmed, so a long
    article is never shortened in storage because of a token limit.
    """
    value = str(text or "")
    if limit <= 0 or len(value) <= limit:
        return value
    return value[:limit].rstrip()


class ArticleContentCache:
    """Bodies already extracted, keyed by canonical URL.

    Only successes are written. A failure is retried on the next refresh, so a
    temporary 503 never becomes permanent.
    """

    def __init__(self, directory: Path | str) -> None:
        self.directory = Path(directory)

    def key(self, canonical_url: str) -> str:
        return hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()

    def path(self, canonical_url: str) -> Path:
        return self.directory / f"{self.key(canonical_url)}.json"

    def get(self, canonical_url: str) -> ArticleContent | None:
        payload = self.raw(canonical_url)
        if payload is None:
            return None
        text = str(payload.get("text") or "")
        if not text:
            return None
        return ArticleContent(
            text=text,
            language=str(payload.get("language") or ""),
            method=str(payload.get("method") or METHOD_WEB),
            from_cache=True,
        )

    def raw(self, canonical_url: str) -> dict | None:
        """The stored JSON for a URL, whatever kind of body it holds."""
        path = self.path(canonical_url)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        return payload if isinstance(payload, dict) else None

    def set(self, canonical_url: str, content: ArticleContent) -> None:
        if not content.text:
            return
        self.store(
            canonical_url,
            {
                "url": canonical_url,
                "text": content.text,
                "language": content.language,
                "method": content.method,
            },
        )

    def store(self, canonical_url: str, payload: dict) -> None:
        """Write one cache entry. Shared with the HTML collectors."""
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            entry = dict(payload)
            entry.setdefault("url", canonical_url)
            entry["fetched_at"] = datetime.now(timezone.utc).isoformat()
            self.path(canonical_url).write_text(
                json.dumps(entry, ensure_ascii=False),
                encoding="utf-8",
                newline="\n",
            )
        except OSError:
            # A cache that cannot be written is a slowdown, not a failure.
            logger.warning("article cache write failed url=%s", canonical_url)


def fetch_article_page(url: str, *, timeout: float = DEFAULT_TIMEOUT) -> FetchResult:
    """Default page fetch. Patched in tests so no suite touches the network."""
    return fetch_document(url, timeout=timeout)


def _is_html(content_type: str) -> bool:
    if not content_type:
        # Some servers omit the header; the body itself is the evidence.
        return True
    return "html" in content_type or "xml" in content_type or content_type == "text/plain"


def _cached(url: str, cache: ArticleContentCache | None) -> ArticleContent | None:
    if cache is None or not url:
        return None
    return cache.get(url)


def extract_article(
    *,
    url: str,
    canonical_url: str = "",
    title: str = "",
    feed_body: str = "",
    feed_summary: str = "",
    settings: ExtractionSettings = DEFAULT_SETTINGS,
    cache: ArticleContentCache | None = None,
    fetch=None,
) -> ArticleContent:
    """Produce the original body for one article, falling back at every step.

    A failure here only ever costs the body, never the article: a page that
    cannot be read ends up with its feed summary, and one bad page never stops
    the refresh.
    """
    cache_key = canonical_url or url
    hit = _cached(cache_key, cache)
    if hit is not None:
        return hit

    # 1. The feed's own full body, when it is long enough to be the article.
    from_feed = clean_html(feed_body, title=title, settings=settings) if feed_body else ""
    if len(from_feed) >= settings.rss_full_min_chars:
        content = ArticleContent(
            text=from_feed,
            language=detect_language(from_feed),
            method=METHOD_RSS_FULL,
        )
        _store(cache, cache_key, content)
        return content

    # 2. The article's own page.
    page_error: str | None = None
    if url:
        try:
            response = (fetch or fetch_article_page)(url, timeout=settings.timeout)
            content_type = str(getattr(response, "content_type", "") or "")
            body = str(getattr(response, "text", "") or "")
            if not _is_html(content_type):
                page_error = f"not HTML ({content_type})"
            elif not body.strip():
                page_error = "empty body"
            else:
                page_text = clean_html(body, title=title, settings=settings)
                if len(page_text) >= settings.web_min_chars:
                    content = ArticleContent(
                        text=page_text,
                        language=detect_language(page_text),
                        method=METHOD_WEB,
                    )
                    _store(cache, cache_key, content)
                    return content
                page_error = f"page too short ({len(page_text)} chars)"
        except FetchError as exc:
            page_error = str(exc)
        except Exception as exc:  # a broken page must not abort the refresh
            page_error = f"{exc.__class__.__name__}: {exc}"
        if page_error:
            logger.debug("article page unusable url=%s error=%s", url, page_error)

    # 3. Whatever the feed gave us: the longer of its body and its description.
    from_summary = clean_html(feed_summary, settings=settings) if feed_summary else ""
    fallback = max((from_feed, from_summary), key=len)
    if fallback:
        return ArticleContent(
            text=fallback,
            language=detect_language(fallback),
            method=METHOD_RSS_SUMMARY,
            error=page_error,
        )
    return ArticleContent(text="", language="", method=METHOD_NONE, error=page_error or "no content")


def _store(cache: ArticleContentCache | None, key: str, content: ArticleContent) -> None:
    if cache is not None and key:
        cache.set(key, content)


@dataclass
class ExtractionDecision:
    """One article's extraction outcome, for the refresh log."""

    source: str
    title: str
    method: str
    chars: int
    error: str | None = None
    from_cache: bool = False

    @property
    def label(self) -> str:
        if self.from_cache:
            return LABEL_CACHE
        if self.method == METHOD_RSS_SUMMARY or self.method == METHOD_NONE:
            return LABEL_FALLBACK
        return self.method.upper()

    def describe(self) -> str:
        line = f"{self.source} | {self.label} | {self.chars} chars"
        if self.error:
            line = f"{line} | {self.error}"
        return line


@dataclass
class ExtractionStats:
    """Counts for one extraction pass. Never contains the body itself."""

    candidates: int = 0
    rss_full: int = 0
    web: int = 0
    fallback: int = 0
    failed: int = 0
    cache_hits: int = 0
    decisions: list[ExtractionDecision] = field(default_factory=list)


def extract_articles(
    articles: list[RawArticle],
    *,
    settings: ExtractionSettings | None = None,
    cache: ArticleContentCache | None = None,
    fetch=None,
) -> tuple[list[RawArticle], ExtractionStats]:
    """Fill in the original body of every article, in order.

    One article's failure is contained: it keeps its feed summary and the loop
    continues.
    """
    resolved = settings or load_extraction_settings()
    resolved_cache = cache
    if resolved_cache is None and resolved.effective_cache_dir is not None:
        resolved_cache = ArticleContentCache(resolved.effective_cache_dir)

    stats = ExtractionStats(candidates=len(articles))
    enriched: list[RawArticle] = []
    for article in articles:
        try:
            content = extract_article(
                url=article.url,
                canonical_url=article.canonical_url,
                title=article.title,
                feed_body=article.feed_body,
                feed_summary=article.summary,
                settings=resolved,
                cache=resolved_cache,
                fetch=fetch,
            )
        except Exception as exc:  # belt and braces: never break the refresh
            logger.exception("article extraction crashed url=%s", article.url)
            content = ArticleContent(
                text=normalize_plain_text(article.summary),
                language=detect_language(article.summary),
                method=METHOD_RSS_SUMMARY,
                error=f"{exc.__class__.__name__}: {exc}",
            )

        if content.from_cache:
            stats.cache_hits += 1
        if content.method == METHOD_RSS_FULL:
            stats.rss_full += 1
        elif content.method == METHOD_WEB:
            stats.web += 1
        else:
            stats.fallback += 1
        if content.error:
            stats.failed += 1

        stats.decisions.append(
            ExtractionDecision(
                source=article.source,
                title=article.title,
                method=content.method,
                chars=len(content.text),
                error=content.error,
                from_cache=content.from_cache,
            )
        )
        enriched.append(
            replace(
                article,
                content=content.text,
                content_language=content.language,
                content_method=content.method,
                content_fetched_at=datetime.now(timezone.utc) if content.text else None,
            )
        )
    return enriched, stats


def format_extraction_stats(stats: ExtractionStats, *, debug: bool = False) -> str:
    """The refresh report. Counts only unless debug asks for per-article lines."""
    lines = [
        "Article extraction:",
        f"Candidates: {stats.candidates}",
        f"RSS full content: {stats.rss_full}",
        f"Web extracted: {stats.web}",
        f"RSS fallback: {stats.fallback}",
        f"Failed: {stats.failed}",
        f"Cache hit: {stats.cache_hits}",
    ]
    if debug:
        lines.append("")
        lines.extend(decision.describe() for decision in stats.decisions)
    return "\n".join(lines)


def log_extraction(stats: ExtractionStats, *, debug: bool = False) -> None:
    """Log a one-line summary, plus per-article detail only in debug mode."""
    if stats.candidates == 0:
        return
    logger.info(
        "article extraction: candidates=%s rss_full=%s web=%s fallback=%s failed=%s cache_hits=%s",
        stats.candidates,
        stats.rss_full,
        stats.web,
        stats.fallback,
        stats.failed,
        stats.cache_hits,
    )
    if not debug:
        return
    for decision in stats.decisions:
        logger.info("article extraction decision: %s", decision.describe())
