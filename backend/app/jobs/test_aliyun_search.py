"""Can Aliyun CleverSee Web Search be the dynamic discovery layer for AI Daily?

    cd backend
    uv run python -m app.jobs.test_aliyun_search

This is the twin of ``app/jobs/test_baidu_search.py``: the same question, the same
queries, the same counting, so the two engines can be compared row by row for
Phase 10.15. Anything that would make the comparison unfair is deliberately
shared, not re-implemented - the query pool, the ``page_time`` date range, the
publish-time parsing, the "last 24 hours" rule, URL canonicalization, the
known-fixed-source test and the report shape all come from the Baidu probe by
import. A second copy of those rules would drift, and a drifting copy is exactly
what a comparison cannot survive.

It calls the CleverSee unified search endpoint
``POST https://cloud-iqs.aliyuncs.com/search/unified`` with ``engineType``
``CNLiteBasic`` and asks for web pages only: ``contents`` switches main text,
markdown and the AI summary off, so the engine returns result metadata rather
than a generated answer. The AI summary is a billed option and is *not* used -
this phase needs candidate URLs, and a model's retelling is not a discovery
signal.

Nothing is integrated. No database, schema, collector, refresh pipeline,
scheduler, source configuration or LLM client is touched, and a search result is
never written anywhere: the flow is CleverSee Search -> candidate URLs ->
printed counts. Results are not news.

Two extra diagnostics exist here that the Baidu probe does not need:

* **source quality** - each result is bucketed as official/company, professional
  media, GitHub/arXiv, portal/repost, UGC/blog or unknown, so the *kind* of
  source each engine prefers is visible. These buckets are a probe-local
  taxonomy: they read the project's ``SOURCES`` but never write to it, and
  nothing may depend on them in business code.
* **the watchlist** - the seven second-hand domains AI Daily does not want
  (baijiahao, 163, zhihu columns, CSDN, sohu, sina, xueqiu) are counted by name.
  They are *not* excluded through ``excludeSites``: the first round has to show
  the raw recall, or the comparison with Baidu would be measuring the filter
  instead of the engine.

The API key is read from ``ALIYUN_SEARCH_API_KEY`` and is never printed, logged or
written to disk.

Exit status: 0 at least one query returned results, 1 no query succeeded (the
endpoint is unusable: rejected key, rate limit, outage), 2 the probe could not
run at all because no key is configured.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

from app.collectors.http import USER_AGENT
from app.config.env import load_dotenv
from app.pipelines.ai_filter import is_ai_related
from app.pipelines.urls import canonicalize_url
from app.services.digest_window import as_utc

# Shared with the Baidu probe on purpose: identical conditions are the whole point
# of running two engines, and a second copy of these rules would drift. See the
# module docstring.
from app.jobs.test_baidu_search import (
    BODY_LIMIT,
    DEFAULT_MAX_QUERY_CHARS,
    DOMAIN_COLUMN,
    LIST_SEPARATOR,
    MAX_DISCOVERED_PRINTED,
    MAX_RESULTS_PRINTED,
    MISSING_CONFIG_EXIT,
    QUERY_POOL,
    SNIPPET_LIMIT,
    TITLE_LIMIT,
    UNUSABLE_EXIT,
    Attempt,
    PublishTime,
    check_query,
    discovery_order,
    domain_of,
    format_publish_time,
    is_known_source_domain,
    is_within_last_24h,
    known_source_domains,
    parse_page_time,
    print_top_domains,
    probe_date_range,
    send_request,
    top_level_keys,
    trim,
)

ENDPOINT = "https://cloud-iqs.aliyuncs.com/search/unified"

# Round one tests exactly one engine. CNLiteBasic is the fast semantic engine and
# the cheapest way to see what the index actually contains; Generic, CNAuto and
# GlobalAdvanced are deliberately left for a later round, because a second engine
# would answer a different question before the first one is understood.
ENGINE_TYPE = "CNLiteBasic"

# CleverSee wants the item count as a *string* (``advancedParams`` is typed
# ``map<string, string>``), and its documented range is 1-50. 10 matches the
# Baidu probe so both engines are asked for the same amount of material.
DEFAULT_NUM_RESULTS = 10

# An advancedParams value, not a number: the service reads a JSON string map.
NUM_RESULTS_AS_STR = str(DEFAULT_NUM_RESULTS)

# Only what the probe needs. ``summary`` and ``mainText`` are billed options and
# would also change the result set the engine considers, so both stay off and the
# probe never sees CleverSee's AI summary.
CONTENTS = {
    "mainText": False,
    "markdownText": False,
    "summary": False,
    "rerankScore": True,
}

# The server gives up after 5 seconds per the API reference, so a longer client
# timeout would only turn a fast server-side failure into slow local waiting.
SERVER_TIMEOUT_NOTE = "the service documents a 5s server-side timeout"
DEFAULT_TIMEOUT = 30.0

# The query cap is imported rather than re-declared, even though this endpoint
# allows 500 characters per the reference. Sharing it means an over-long query is
# skipped identically in both probes, so neither engine is measured on a query the
# other dropped.

# --- result field names ---------------------------------------------------- #
#
# Taken from the CleverSee UnifiedSearch reference. ``link`` is the address and
# ``hostname`` is the *site name* ("云栖大会"), not a domain, so the hostname used
# for statistics is always derived from ``link``; the site name is kept for
# display only. Every read is tolerant: a missing field never drops a result.
TITLE_KEYS = ("title",)
URL_KEYS = ("link", "url")
SITE_KEYS = ("hostname", "siteName", "site", "source")
PUBLISHED_KEYS = ("publishedTime", "published_at", "publishTime", "pubTime", "date")
SNIPPET_KEYS = ("snippet", "summary", "description", "mainText")
SCORE_KEYS = ("rerankScore", "rerank_score", "score")
TAG_KEYS = ("tags", "tag")

# The item list. ``pageItems`` is documented; the rest are tolerated so a rename
# shows up as a readable message instead of a crash.
PAGE_ITEM_KEYS = ("pageItems", "items", "results", "documents", "data")

# The tag values the reference documents: genre / isUgc / ugcType / industry /
# isListPage. They arrive as strings, so "true" is as likely as true.
GENRE_KEY = "genre"
UGC_KEY = "isUgc"
UGC_TYPE_KEY = "ugcType"
INDUSTRY_KEY = "industry"
LIST_PAGE_KEY = "isListPage"

TRUE_STRINGS = {"true", "1", "yes", "y"}
FALSE_STRINGS = {"false", "0", "no", "n"}

# --------------------------------------------------------------------------- #
# request payload
# --------------------------------------------------------------------------- #


def build_payload(
    query: str,
    start_date: str,
    end_date: str,
    *,
    num_results: int = DEFAULT_NUM_RESULTS,
    engine_type: str = ENGINE_TYPE,
) -> dict:
    """The request body for one query, as the UnifiedSearch reference defines it.

    ``advancedParams`` is a string map per the reference, so ``numResults`` is a
    string, not an integer. The date bounds are the same yesterday-through-today
    range the Baidu probe asks for, which is a *date* range and not a 24h window
    (the precise check is local, see ``is_within_last_24h``).

    Included attributes: ``startPublishedDate`` / ``endPublishedDate``,
    ``includeSites`` / ``excludeSites``, plus ``timeRange`` are the documented
    other inputs. ``excludeSites`` is the documented leverage point for the
    watchlist, and it is deliberately unused in round one: excluding the
    second-hand domains would hide exactly the contamination this probe exists to
    measure, and the comparison with Baidu would then be measuring the filter
    instead of the engine. ``includeSites`` would do the same in the other
    direction by narrowing recall to sources the project already knows.
    """
    return {
        "query": query,
        "engineType": engine_type,
        "contents": dict(CONTENTS),
        "advancedParams": {
            "numResults": str(num_results),
            "startPublishedDate": start_date,
            "endPublishedDate": end_date,
        },
    }


# --------------------------------------------------------------------------- #
# response parsing
# --------------------------------------------------------------------------- #


@dataclass
class RawResult:
    """One entry from ``pageItems``, before anything is derived from it."""

    title: str = ""
    url: str = ""
    site: str = ""
    published: str = ""
    snippet: str = ""
    rerank_score: str = ""
    tags: dict[str, str] = field(default_factory=dict)


@dataclass
class ParsedResponse:
    """What one response body yielded."""

    found: bool = False
    list_key: str = ""
    results: list[RawResult] = field(default_factory=list)
    skipped_no_url: int = 0


def _first_text(node: Mapping[str, Any], keys: Sequence[str]) -> str:
    """The first non-empty scalar under ``keys``, as text."""
    for key in keys:
        value = node.get(key)
        if isinstance(value, (str, int, float)) and str(value).strip():
            return str(value).strip()
    return ""


def _as_text(value: Any) -> str:
    """A tag value flattened to text, tolerating numbers and booleans."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value).strip()
    return ""


def normalize_tags(value: Any) -> dict[str, str]:
    """The ``tags`` map flattened to text, with unknown keys kept.

    The reference types tags as ``Map<String, String>`` and documents genre /
    isUgc / ugcType / industry / isListPage, but it also warns the data is
    incomplete. Nothing here filters by key or value: a tag the probe does not
    recognise is still shown, because dropping it would hide a field rename, and
    the reference is explicit that an absent tag does not mean anything.
    """
    if not isinstance(value, Mapping):
        return {}
    tags: dict[str, str] = {}
    for key, raw in value.items():
        text = _as_text(raw)
        if text:
            tags[str(key)] = text
    return tags


def find_page_items(payload: Any, *, _depth: int = 0) -> tuple[list | None, str]:
    """The ``pageItems`` list and the key it was found under.

    ``None`` means "no item list here", which is a reading failure and is
    reported as one; an empty list means the query genuinely matched nothing.
    Those two must not collapse into the same report, or a schema change would
    silently look like a quiet news day.
    """
    if not isinstance(payload, dict) or _depth > 2:
        return None, ""
    for key in PAGE_ITEM_KEYS:
        if key not in payload:
            continue
        value = payload[key]
        if isinstance(value, list) and (not value or any(isinstance(item, dict) for item in value)):
            return value, key
        if isinstance(value, dict):
            nested, path = find_page_items(value, _depth=_depth + 1)
            if nested is not None:
                return nested, f"{key}.{path}" if path else key
    return None, ""


def parse_search_response(payload: Any) -> ParsedResponse:
    """Read one response body into results.

    A missing field never sinks the response: an entry without a title keeps an
    empty title, an entry without ``publishedTime`` is reported as unknown, and an
    entry without tags keeps an empty map. Only an entry with no address at all is
    dropped - a URL is the entire point of a discovery probe - and the drop is
    counted so it stays visible.
    """
    parsed = ParsedResponse()
    nodes, key = find_page_items(payload)
    if nodes is None:
        return parsed

    parsed.found = True
    parsed.list_key = key
    for node in nodes:
        if not isinstance(node, dict):
            parsed.skipped_no_url += 1
            continue
        url = _first_text(node, URL_KEYS)
        if not url:
            parsed.skipped_no_url += 1
            continue
        parsed.results.append(
            RawResult(
                title=_first_text(node, TITLE_KEYS),
                url=url,
                site=_first_text(node, SITE_KEYS),
                published=_first_text(node, PUBLISHED_KEYS),
                snippet=_first_text(node, SNIPPET_KEYS),
                rerank_score=_first_text(node, SCORE_KEYS),
                tags=normalize_tags(_first_value(node, TAG_KEYS)),
            )
        )
    return parsed


def _first_value(node: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in node:
            value = node.get(key)
            if value not in (None, "", [], {}):
                return value
    return None


def tag_of(tags: Mapping[str, str], key: str) -> str:
    """One tag value, case-insensitively matched on the key."""
    wanted = key.lower()
    for name, value in tags.items():
        if name.lower() == wanted:
            return value
    return ""


def is_ugc(tags: Mapping[str, str]) -> bool:
    """Whether the tags mark this page as user-generated content.

    ``isUgc`` arrives as the string ``"true"``. Absent or unrecognised values
    return False rather than guessing, matching the reference's warning that tags
    are incomplete and must not be treated as authoritative.
    """
    value = tag_of(tags, UGC_KEY).strip().lower()
    return value in TRUE_STRINGS


def format_tags(tags: Mapping[str, str]) -> str:
    """A compact one-line rendering of the tags for the terminal."""
    if not tags:
        return "(none)"
    return " ".join(f"{key}={value}" for key, value in sorted(tags.items()))

def error_message(payload: Any) -> str:
    """CleverSee's error text, if the body carries one.

    Verified against the live endpoint: an invalid key answers HTTP 403 with
    ``{"requestId": ..., "errorMessage": ..., "errorCode": "Retrieval.InvalidAPIKey"}``.
    The ``errorCode`` is kept because it is the part worth quoting in a report.
    """
    if not isinstance(payload, dict):
        return ""
    code = payload.get("errorCode") or payload.get("code")
    for key in ("errorMessage", "error_msg", "message", "msg"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            text = value.strip()
            return f"{text} (code {code})" if code else text
    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message") or error.get("msg") or error.get("code")
        if isinstance(message, str) and message.strip():
            return message.strip()
        return json.dumps(error, ensure_ascii=False)[:BODY_LIMIT]
    if isinstance(error, str) and error.strip():
        return error.strip()
    if code:
        return str(code)
    return ""


def describe_failure(attempt: Attempt) -> str:
    """One readable line for a query that produced no results."""
    if attempt.status_code is None:
        return attempt.transport_error or "the request never reached the server"

    status = attempt.status_code
    message = error_message(attempt.payload)
    detail = f": {message}" if message else ""
    if status in (401, 403):
        return f"HTTP {status}: the API key was rejected{detail}"
    if status == 429:
        return f"HTTP 429: rate limited, and the probe does not retry{detail}"
    if status == 400:
        return f"HTTP 400: the request was rejected{detail}"
    if status >= 500:
        return f"HTTP {status}: Aliyun failed{detail}"
    if status >= 400:
        return f"HTTP {status}: unexpected failure{detail}"
    if not attempt.parsed:
        return f"HTTP {status}: the body is not JSON, so no results could be read ({attempt.body_preview})"
    keys = top_level_keys(attempt.payload)
    return f"HTTP {status}: no result list in the response (top-level keys: {keys})"


# --------------------------------------------------------------------------- #
# source quality (probe-local taxonomy)
# --------------------------------------------------------------------------- #

# The buckets the report prints. They are a *description* used to compare two
# engines, not a classification the product uses: the project keeps its own
# source_type (official / research / media) in app/config/sources.py and this
# probe never reads from or writes to it, and no business rule may depend on
# these names.
OFFICIAL = "Official/company domains"
PROFESSIONAL_MEDIA = "Professional media"
RESEARCH = "GitHub/arXiv"
PORTAL = "Portal/repost"
UGC_BLOG = "UGC/blog"
UNKNOWN_QUALITY = "Unknown"

SOURCE_QUALITY_ORDER = (OFFICIAL, PROFESSIONAL_MEDIA, RESEARCH, PORTAL, UGC_BLOG, UNKNOWN_QUALITY)

# Sites that republish other people's reporting or host user-generated content.
# Every entry is a *hostname suffix* matched on a dot boundary, so
# ``m.163.com`` and ``epaper.163.com`` are both covered by ``163.com``, and
# ``not163.com`` is not.
PORTAL_DOMAINS = (
    "baijiahao.baidu.com",
    "163.com",
    "sohu.com",
    "sina.com.cn",
    "sina.cn",
    "qq.com",
    "ifeng.com",
    "toutiao.com",
    "thepaper.cn",
    "eastday.com",
    "huanqiu.com",
    "chinanews.com",
    "people.com.cn",
    "xinhuanet.com",
    "cctv.com",
    "yicai.com",
    "jiemian.com",
    "cls.cn",
    "stcn.com",
    "cnstock.com",
    "hexun.com",
    "jrj.com.cn",
)

UGC_DOMAINS = (
    "zhuanlan.zhihu.com",
    "zhihu.com",
    "blog.csdn.net",
    "csdn.net",
    "juejin.cn",
    "cnblogs.com",
    "segmentfault.com",
    "jianshu.com",
    "toutiao.com",
    "weibo.com",
    "weixin.qq.com",
    "mp.weixin.qq.com",
    "xiaohongshu.com",
    "douban.com",
    "tieba.baidu.com",
    "zhidao.baidu.com",
    "baike.baidu.com",
    "wenku.baidu.com",
    "reddit.com",
    "medium.com",
    "substack.com",
    "dev.to",
    "news.ycombinator.com",
    "v2ex.com",
    "oschina.net",
    "51cto.com",
    "xueqiu.com",
    "bilibili.com",
    "douyin.com",
    "youtube.com",
    "wordpress.com",
    "blogspot.com",
    "github.io",
)

RESEARCH_DOMAINS = (
    "github.com",
    "arxiv.org",
    "huggingface.co",
    "paperswithcode.com",
    "openreview.net",
    "acm.org",
    "ieee.org",
    "nature.com",
    "science.org",
    "springer.com",
    "sciencedirect.com",
    "semanticscholar.org",
    "biorxiv.org",
    "ssrn.com",
)

MEDIA_DOMAINS = (
    "techcrunch.com",
    "theverge.com",
    "wired.com",
    "arstechnica.com",
    "venturebeat.com",
    "theregister.com",
    "zdnet.com",
    "cnet.com",
    "engadget.com",
    "bloomberg.com",
    "reuters.com",
    "ft.com",
    "wsj.com",
    "nytimes.com",
    "theinformation.com",
    "businessinsider.com",
    "cnbc.com",
    "forbes.com",
    "technologyreview.com",
    "newscientist.com",
    "quantamagazine.org",
    "spectrum.ieee.org",
    "marktechpost.com",
    "syncedreview.com",
    "jiqizhixin.com",
)

# The seven domains the project wants to know about by name. They are reported
# separately from the buckets because "half the results are second-hand
# aggregators" is the single fact that decides whether this engine is usable.
SECOND_HAND_DOMAINS = (
    "baijiahao.baidu.com",
    "163.com",
    "zhuanlan.zhihu.com",
    "blog.csdn.net",
    "sohu.com",
    "sina.com.cn",
    "xueqiu.com",
)


def _matches_suffix(domain: str, suffixes: Sequence[str]) -> bool:
    """Whether ``domain`` is one of ``suffixes`` or a subdomain of one."""
    if not domain:
        return False
    return any(domain == suffix or domain.endswith(f".{suffix}") for suffix in suffixes)


def watched_domain_of(domain: str) -> str:
    """The watchlist entry a hostname belongs to, or an empty string.

    Results are grouped under the watchlist entry rather than the raw hostname, so
    ``baijiahao.baidu.com`` and ``m.163.com`` report as ``baijiahao.baidu.com`` and
    ``163.com``: a site reachable on several subdomains is one source, and
    splitting it across ``m.163.com`` / ``www.163.com`` would understate the
    contamination this probe is measuring.
    """
    if not domain:
        return ""
    for watched in SECOND_HAND_DOMAINS:
        if domain == watched or domain.endswith(f".{watched}"):
            return watched
    return ""


def is_second_hand_domain(domain: str) -> bool:
    """Whether the hostname is one of the seven watched aggregator/UGC domains."""
    return bool(watched_domain_of(domain))


def classify_source(
    domain: str,
    *,
    tags: Mapping[str, str] | None = None,
    known: frozenset[str] | None = None,
) -> str:
    """Which quality bucket a result's hostname falls into.

    Order matters and is deliberate. The project's own configured sources win
    first, because those are the first-party domains AI Daily already trusts and
    reporting them as "unknown" would understate the engine's quality. Then the
    watched aggregators, research hosts and media, and only then the engine's own
    ``isUgc`` tag. The tag comes last because the reference warns it is
    incomplete; a tagged UGC page on a watched domain is still counted as the
    watched domain, which is the conservative answer.
    """
    configured = known if known is not None else known_source_domains()
    if domain and is_known_source_domain(domain, configured):
        return OFFICIAL
    if _matches_suffix(domain, PORTAL_DOMAINS):
        return PORTAL
    if _matches_suffix(domain, UGC_DOMAINS):
        return UGC_BLOG
    if _matches_suffix(domain, RESEARCH_DOMAINS):
        return RESEARCH
    if _matches_suffix(domain, MEDIA_DOMAINS):
        return PROFESSIONAL_MEDIA
    if tags and is_ugc(tags):
        return UGC_BLOG
    return UNKNOWN_QUALITY

# --------------------------------------------------------------------------- #
# collected results and statistics
# --------------------------------------------------------------------------- #


@dataclass
class SearchResult:
    """A result with everything the report needs already derived from it."""

    query: str = ""
    title: str = ""
    url: str = ""
    canonical_url: str = ""
    domain: str = ""
    site: str = ""
    snippet: str = ""
    page_time: PublishTime = field(default_factory=PublishTime)
    known_source: bool = False
    rerank_score: str = ""
    tags: dict[str, str] = field(default_factory=dict)
    quality: str = UNKNOWN_QUALITY

    @property
    def genre(self) -> str:
        return tag_of(self.tags, GENRE_KEY)


@dataclass
class QueryOutcome:
    """How one query went."""

    query: str = ""
    skipped: str = ""
    attempt: Attempt | None = None
    results: list[SearchResult] = field(default_factory=list)
    error: str = ""
    skipped_no_url: int = 0

    @property
    def status_code(self) -> int | None:
        return self.attempt.status_code if self.attempt else None


def to_search_result(raw: RawResult, query: str, known: frozenset[str]) -> SearchResult:
    """Derive everything the report needs from one raw entry.

    The domain comes from ``link``, never from ``hostname``: the reference defines
    ``hostname`` as the site *name* ("云栖大会"), so using it as a hostname would
    silently produce nonsense domains and make every downstream count wrong.
    """
    domain = domain_of(raw.url)
    return SearchResult(
        query=query,
        title=raw.title,
        url=raw.url,
        canonical_url=canonicalize_url(raw.url),
        domain=domain,
        site=raw.site or domain,
        snippet=raw.snippet,
        page_time=parse_page_time(raw.published),
        known_source=is_known_source_domain(domain, known),
        rerank_score=raw.rerank_score,
        tags=raw.tags,
        quality=classify_source(domain, tags=raw.tags, known=known),
    )


@dataclass
class Summary:
    """Every number the final report prints."""

    engine: str = ENGINE_TYPE
    queries: int = 0
    successful: int = 0
    failed: int = 0
    skipped: int = 0
    raw_results: int = 0
    duplicates: int = 0
    published_known: int = 0
    inside_24h: int = 0
    outside_24h: int = 0
    unknown_publish: int = 0
    known_sources: int = 0
    discovered: int = 0
    domains: Counter = field(default_factory=Counter)
    quality: Counter = field(default_factory=Counter)
    watched: Counter = field(default_factory=Counter)
    genres: Counter = field(default_factory=Counter)
    tagged: int = 0
    unique_results: list[SearchResult] = field(default_factory=list)
    irrelevant: list[SearchResult] = field(default_factory=list)

    @property
    def unique_urls(self) -> int:
        return len(self.unique_results)

    @property
    def unique_domains(self) -> int:
        return len(self.domains)

    @property
    def second_hand(self) -> int:
        return sum(self.watched.values())


def summarize(outcomes: Sequence[QueryOutcome], now: datetime, *, engine: str = ENGINE_TYPE) -> Summary:
    """Count what the queries found. The same URL from two queries counts once.

    Deduplication, the recency buckets and the known-source split are the same
    rules the Baidu probe uses (``canonicalize_url``, ``is_within_last_24h``,
    ``is_known_source_domain``), so the two summaries are directly comparable.
    The duplicate count is a lower bound: canonicalization only removes the
    tracking parameters the project already knows about.
    """
    summary = Summary(engine=engine, queries=len(outcomes))
    seen: dict[str, SearchResult] = {}
    reported: set[str] = set()

    for outcome in outcomes:
        if outcome.skipped:
            summary.skipped += 1
            continue
        if outcome.error:
            summary.failed += 1
            continue
        summary.successful += 1
        for result in outcome.results:
            summary.raw_results += 1
            key = result.canonical_url or result.url
            if key in reported:
                summary.duplicates += 1
                continue
            reported.add(key)
            seen[key] = result

    summary.unique_results = list(seen.values())
    for result in summary.unique_results:
        summary.domains[result.domain or "(no host)"] += 1
        summary.quality[result.quality] += 1
        if result.tags:
            summary.tagged += 1
        if result.genre:
            summary.genres[result.genre] += 1
        watched = watched_domain_of(result.domain)
        if watched:
            summary.watched[watched] += 1

        if result.known_source:
            summary.known_sources += 1
        else:
            summary.discovered += 1

        moment = result.page_time.moment
        if moment is not None:
            summary.published_known += 1
        if moment is not None and result.page_time.has_time:
            if is_within_last_24h(moment, now):
                summary.inside_24h += 1
            else:
                summary.outside_24h += 1
        else:
            summary.unknown_publish += 1

        if not is_ai_related(result.title, result.snippet):
            summary.irrelevant.append(result)

    return summary


def candidate_order(result: SearchResult, now: datetime) -> tuple:
    """Discovery order, with the engine's own relevance score as the tie-break.

    ``discovery_order`` from the Baidu probe decides first (inside 24h, then known
    times, then newest), so both probes list candidates in the same order. Only
    results that tie on all of that are separated by ``rerankScore``, which is a
    CleverSee-specific signal and therefore must not outrank the shared rules.
    """
    score = _score_as_float(result.rerank_score)
    return (*discovery_order(result, now), -score)


def _score_as_float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0

# --------------------------------------------------------------------------- #
# output
# --------------------------------------------------------------------------- #


def print_header(
    out: Callable[[str], None],
    query_count: int,
    configured: bool,
    start: str,
    end: str,
    timeout: float,
    num_results: int,
) -> None:
    out("Aliyun CleverSee Web Search Probe")
    out(f"Endpoint: {ENDPOINT}")
    out(f"Engine: {ENGINE_TYPE}")
    out(f"Queries: {query_count}")
    out(f"API key: {'configured' if configured else 'missing'}")
    out(f"Page time range: {start} .. {end} (a date range, not a 24h guarantee)")
    out(f"Timeout: {timeout:g}s   numResults: {num_results}   ({SERVER_TIMEOUT_NOTE})")
    out("")


def print_query_outcome(outcome: QueryOutcome, out: Callable[[str], None]) -> None:
    out(LIST_SEPARATOR)
    out(f"QUERY: {outcome.query}")
    if outcome.skipped:
        out(f"SKIPPED: {outcome.skipped}")
        out("")
        return

    out(f"HTTP: {outcome.status_code if outcome.status_code is not None else 'no response'}")
    if outcome.error:
        out(f"Failure: {outcome.error}")
        out("")
        return

    suffix = f" ({outcome.skipped_no_url} without a URL, skipped)" if outcome.skipped_no_url else ""
    out(f"Results: {len(outcome.results)}{suffix}")
    out("")
    for index, result in enumerate(outcome.results[:MAX_RESULTS_PRINTED], start=1):
        out(f"{index}. {trim(result.title, TITLE_LIMIT) or '(no title)'}")
        out(f"   domain: {result.domain or '(unknown)'}")
        out(f"   published: {format_publish_time(result.page_time)}")
        out(f"   rerank_score: {result.rerank_score or '(none)'}")
        out(f"   tags: {format_tags(result.tags)}")
        out(f"   url: {result.url}")
        out(f"   snippet: {trim(result.snippet, SNIPPET_LIMIT) or '(no snippet)'}")
        out("")


def print_summary(summary: Summary, out: Callable[[str], None]) -> None:
    out(LIST_SEPARATOR)
    out("SUMMARY")
    out("")
    out(f"Engine: {summary.engine}")
    out("")
    out(f"Queries: {summary.queries}")
    out(f"Successful: {summary.successful}")
    out(f"Failed: {summary.failed}")
    out(f"Skipped (over the query length limit): {summary.skipped}")
    out("")
    out(f"Raw results: {summary.raw_results}")
    out(f"Unique URLs: {summary.unique_urls}")
    out(f"Duplicate URLs: {summary.duplicates}")
    out("")
    out(f"Published time available: {summary.published_known}")
    out(f"Inside last 24h: {summary.inside_24h}")
    out(f"Outside last 24h: {summary.outside_24h}")
    out(f"Unknown publish time: {summary.unknown_publish}")
    out("")
    out(f"Unique domains: {summary.unique_domains}")
    out("")
    out(f"Known fixed-source URLs: {summary.known_sources}")
    out(f"New/discovered URLs: {summary.discovered}")


def print_source_quality(summary: Summary, out: Callable[[str], None]) -> None:
    """The buckets, the second-hand watchlist and the engine's own tags.

    Reported in ``SOURCE_QUALITY_ORDER`` rather than by count, so two runs (or two
    engines) line up row for row.
    """
    out("")
    out(LIST_SEPARATOR)
    out("SOURCE QUALITY (probe analysis only)")
    out("")
    out("Probe-local buckets. Nothing here writes to app/config/sources.py and no")
    out("business rule may depend on these names.")
    out("")
    total = sum(summary.quality.values())
    for bucket in SOURCE_QUALITY_ORDER:
        count = summary.quality.get(bucket, 0)
        share = f"{100 * count / total:5.1f}%" if total else "    -"
        out(f"{bucket:<{DOMAIN_COLUMN}} {count:>4}  {share}")
    out(f"{'TOTAL':<{DOMAIN_COLUMN}} {total:>4}")

    out("")
    out("Second-hand / UGC watchlist (not excluded from the request):")
    if not summary.watched:
        out("  (none of the watched domains appeared)")
    else:
        for domain in SECOND_HAND_DOMAINS:
            count = summary.watched.get(domain, 0)
            if count:
                out(f"  {domain:<{DOMAIN_COLUMN}} {count}")
        out(f"  {'watched total':<{DOMAIN_COLUMN}} {summary.second_hand} of {total} unique results")

    out("")
    out(f"Results carrying tags: {summary.tagged} of {total}")
    out("Genre distribution (tags.genre):")
    if not summary.genres:
        out("  (no genre tags returned)")
    for genre, count in summary.genres.most_common():
        out(f"  {genre:<{DOMAIN_COLUMN}} {count}")
    out("")
    out("Genre is printed for diagnosis only. Docs warn tags are incomplete, so an")
    out("absent tag is not evidence of anything and round one must not filter on it.")


def print_candidates(summary: Summary, now: datetime, out: Callable[[str], None]) -> None:
    discovered = [result for result in summary.unique_results if not result.known_source]
    discovered.sort(key=lambda result: candidate_order(result, now))

    out("")
    out(LIST_SEPARATOR)
    out("DISCOVERED CANDIDATES")
    out("")
    out("Hostnames the fixed sources do not cover, most recent first.")
    out("")
    if not discovered:
        if summary.unique_urls:
            out("(none - every hostname returned is already a configured source)")
        else:
            out("(no results to compare)")
        return
    for index, result in enumerate(discovered[:MAX_DISCOVERED_PRINTED], start=1):
        out(f"{index}. {trim(result.title, TITLE_LIMIT) or '(no title)'}")
        out(f"   domain: {result.domain or '(unknown)'}")
        out(f"   published: {format_publish_time(result.page_time)}")
        out(f"   rerank_score: {result.rerank_score or '(none)'}")
        out(f"   tags: {format_tags(result.tags)}")
        out(f"   url: {result.url}")
        out("")


def print_relevance(summary: Summary, out: Callable[[str], None]) -> None:
    """Results the project's own AI evidence rule would not accept.

    Reusing ``app.pipelines.ai_filter`` keeps the number reproducible. It is a
    hint: the word lists are English plus Chinese brand names, so a Chinese story
    about 人工智能 with no model name is counted here as well.
    """
    out("")
    out(LIST_SEPARATOR)
    out("AI RELEVANCE (diagnostic)")
    out("")
    out(f"Unique results without AI evidence (app/pipelines/ai_filter): {len(summary.irrelevant)}")
    out("Hint only: those word lists are English plus Chinese brand names, so a Chinese")
    out("story about 人工智能 / 具身智能 with no model name is counted here as well.")
    for result in summary.irrelevant[:5]:
        out(f"  - {trim(result.title, TITLE_LIMIT) or '(no title)'} ({result.domain or 'no host'})")


def render_report(summary: Summary, now: datetime, out: Callable[[str], None]) -> None:
    """The part of the report that can only be printed once every query is in.

    Per-query output is not repeated here: it is already printed as each query
    finishes, so a slow run still shows progress instead of staying silent.
    """
    print_summary(summary, out)
    print_top_domains(summary, out)
    print_source_quality(summary, out)
    print_candidates(summary, now, out)
    print_relevance(summary, out)

# --------------------------------------------------------------------------- #
# entry points
# --------------------------------------------------------------------------- #


def api_key_from_env() -> str:
    return os.getenv("ALIYUN_SEARCH_API_KEY", "").strip()


def run(
    *,
    api_key: str,
    queries: Sequence[str] = QUERY_POOL,
    endpoint: str = ENDPOINT,
    engine_type: str = ENGINE_TYPE,
    timeout: float = DEFAULT_TIMEOUT,
    num_results: int = DEFAULT_NUM_RESULTS,
    max_query_chars: int = DEFAULT_MAX_QUERY_CHARS,
    now: datetime | None = None,
    send: Callable[[str, dict, dict, float], Attempt] | None = None,
    out: Callable[[str], None] = print,
) -> int:
    """Run every query and print the report. Returns the exit status.

    One query failing never stops the next one: discovery is being measured, and
    dropping nine queries because the first hit a 429 would produce a report about
    nothing.
    """
    transport = send or send_request
    started = as_utc(now or datetime.now(timezone.utc))
    start_date, end_date = probe_date_range(started)
    known = known_source_domains()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }

    print_header(out, len(queries), bool(api_key), start_date, end_date, timeout, num_results)

    outcomes: list[QueryOutcome] = []
    for query in queries:
        outcome = QueryOutcome(query=query)
        skip_reason = check_query(query, max_query_chars)
        if skip_reason:
            outcome.skipped = skip_reason
            outcomes.append(outcome)
            print_query_outcome(outcome, out)
            continue

        payload = build_payload(query, start_date, end_date, num_results=num_results, engine_type=engine_type)
        attempt = transport(endpoint, headers, payload, timeout)
        outcome.attempt = attempt
        if attempt.status_code != 200 or not attempt.parsed:
            outcome.error = describe_failure(attempt)
        else:
            parsed = parse_search_response(attempt.payload)
            if not parsed.found:
                outcome.error = describe_failure(attempt)
            else:
                outcome.skipped_no_url = parsed.skipped_no_url
                outcome.results = [to_search_result(raw, query, known) for raw in parsed.results]

        outcomes.append(outcome)
        print_query_outcome(outcome, out)

    summary = summarize(outcomes, started, engine=engine_type)
    render_report(summary, started, out)
    return 0 if summary.successful else UNUSABLE_EXIT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Probe the Aliyun CleverSee Web Search API as a discovery layer for AI Daily"
    )
    parser.add_argument(
        "--engine",
        default=ENGINE_TYPE,
        help=f"engineType to request (round one tests only {ENGINE_TYPE})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"seconds to wait for each response (default: {DEFAULT_TIMEOUT:g})",
    )
    parser.add_argument(
        "--num-results",
        type=int,
        default=DEFAULT_NUM_RESULTS,
        help=f"results to request per query (default: {DEFAULT_NUM_RESULTS})",
    )
    parser.add_argument(
        "--max-query-chars",
        type=int,
        default=DEFAULT_MAX_QUERY_CHARS,
        help=f"skip a query longer than this (default: {DEFAULT_MAX_QUERY_CHARS})",
    )
    parser.add_argument("--dump-json", action="store_true", help="print the first raw response JSON")
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    load_dotenv()
    api_key = api_key_from_env()
    if not api_key:
        print("Aliyun CleverSee Web Search Probe")
        print(f"Endpoint: {ENDPOINT}")
        print(f"Engine: {args.engine}")
        print()
        print("Missing environment variable: ALIYUN_SEARCH_API_KEY")
        print("Set it in backend/.env (copy backend/.env.example) or in the environment.")
        return MISSING_CONFIG_EXIT

    if not args.dump_json:
        return run(
            api_key=api_key,
            engine_type=args.engine,
            timeout=args.timeout,
            num_results=args.num_results,
            max_query_chars=args.max_query_chars,
        )

    return _run_with_dump(api_key, args)


def _run_with_dump(api_key: str, args: argparse.Namespace) -> int:
    """The same probe with the first raw response printed, for schema work."""
    first_payload: list[dict] = []

    def send_with_dump(url: str, headers: dict, payload: dict, timeout: float) -> Attempt:
        attempt = send_request(url, headers, payload, timeout)
        if not first_payload and attempt.payload is not None:
            first_payload.append(attempt.payload)
        return attempt

    status = run(
        api_key=api_key,
        engine_type=args.engine,
        timeout=args.timeout,
        num_results=args.num_results,
        max_query_chars=args.max_query_chars,
        send=send_with_dump,
    )
    if first_payload:
        print()
        print("RAW RESPONSE (first query)")
        print("-------------------------")
        print(json.dumps(first_payload[0], ensure_ascii=False, indent=2))
    return status


if __name__ == "__main__":
    raise SystemExit(main())