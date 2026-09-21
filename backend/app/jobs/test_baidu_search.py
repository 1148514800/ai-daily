"""Can Baidu Web Search be the dynamic discovery layer for AI Daily?

    cd backend
    uv run python -m app.jobs.test_baidu_search

This is a probe, not a feature. It answers one question for Phase 10.15: *can
Baidu's Web Search find valuable AI pages that the fixed sources in
``app/config/sources.py`` do not already cover?* It calls the official Baidu AI
Search endpoint ``POST https://qianfan.baidubce.com/v2/ai_search/web_search``
with the queries in :data:`QUERY_POOL` and prints what comes back.

Nothing is integrated. The probe never touches the database, the collectors, the
refresh pipeline, the LLM client, the scheduler or the source configuration, and
it never writes a search result anywhere: results become candidate URLs, are
printed, and are counted. A search result is not news until a later phase says
so, and that phase is not this one.

Two things are measured, because they decide whether such a phase is worth
building:

* **recency** - the API filters by *date* (``page_time``), so the request asks
  for yesterday through today. That range is not "the last 24 hours": whether a
  result really falls inside the last 24 hours is decided locally, from the
  timestamp the response actually carries.
* **novelty** - every URL's hostname is compared with the configured sources, so
  "already covered" and "discovered" are counted separately.

The API key is read from ``BAIDU_SEARCH_API_KEY`` and is never printed, logged or
written to disk.

Exit status: 0 at least one query returned results, 1 no query succeeded (the
endpoint is unusable: rejected key, rate limit, outage), 2 the probe could not
run at all because no key is configured.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Sequence
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx

from app.collectors.http import USER_AGENT
from app.config.discovery import DISCOVERY_QUERIES
from app.config.env import load_dotenv
from app.config.sources import SOURCES
from app.config.timezone import app_timezone
from app.pipelines.ai_filter import is_ai_related
from app.pipelines.urls import canonicalize_url
from app.services.digest_window import as_utc, is_future

ENDPOINT = "https://qianfan.baidubce.com/v2/ai_search/web_search"

# The payload is the shape Baidu documents for this endpoint. ``search_source``
# selects the official v2 search (never the older Baidu Search API), and
# ``resource_type_filter`` asks for web pages only: the first phase of AI Daily
# needs URLs, so video / image / aladdin answers would only add noise. AI
# summarisation is deliberately not requested either - the probe reads the raw
# results, not a model's retelling of them.
SEARCH_SOURCE = "baidu_search_v2"
EDITION = "standard"
RESOURCE_TYPE = "web"
SORT_PRIORITY = "auto"

# A date range, not an hour range: ``page_time`` is filtered by day, so
# "yesterday through today" is the narrowest range that can contain a 24h window.
DATE_FORMAT = "%Y-%m-%d"

# The pool is imported from production rather than duplicated here, so the three
# benchmark probes and the refresh all measure the same queries and their results
# stay comparable. One query is one request, so the pool stays small. It covers
# the product angles AI Daily actually reports on (models, agents, coding agents,
# robots, chips) in both Chinese and English, and names several Chinese vendors
# because the fixed sources are strongest on English first-party blogs.
QUERY_POOL: tuple[str, ...] = DISCOVERY_QUERIES

DEFAULT_TIMEOUT = 30.0
DEFAULT_TOP_K = 10

# Guard against a query the endpoint would reject for its length. No documented
# figure has been confirmed for this endpoint, so this is a deliberately low
# local cap rather than a claim about the API: every query in QUERY_POOL is well
# under it, and a query that exceeds it is *reported and skipped*, never sent.
# Spending free quota on a request that can only fail is exactly what this probe
# avoids, and ``--max-query-chars`` raises the cap once a real limit is known.
DEFAULT_MAX_QUERY_CHARS = 60

BODY_LIMIT = 300
TITLE_LIMIT = 160
SNIPPET_LIMIT = 240
DOMAIN_COLUMN = 32
KEY_LIMIT = 12
MAX_RESULTS_PRINTED = 10
MAX_DISCOVERED_PRINTED = 20
MAX_IRRELEVANT_SAMPLES = 5

MISSING_CONFIG_EXIT = 2
UNUSABLE_EXIT = 1

# Field names the endpoint has been documented to use, most likely first. The
# response schema is not ours, so every read goes through one of these lists and
# a missing field degrades to an empty string instead of dropping the response.
TITLE_KEYS = ("title", "name", "headline")
URL_KEYS = ("url", "link", "href")
SITE_KEYS = ("website", "site", "site_name", "source", "source_name", "web_anchor")
PUBLISHED_KEYS = ("page_time", "date", "publish_time", "published_at", "pub_time", "time", "timestamp")
SNIPPET_KEYS = ("snippet", "content", "summary", "abstract", "description", "desc", "text")

# The key holding the web result list, most likely first. ``references`` is what
# the current endpoint returns; the rest are tolerated so a rename shows up as a
# readable "no results list" message instead of a crash.
RESULT_LIST_KEYS = (
    "references",
    "results",
    "web_results",
    "search_results",
    "items",
    "docs",
    "documents",
    "data",
)

LIST_SEPARATOR = "=" * 60

ISO_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CJK_DATE = re.compile(
    r"^(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
    r"(?:\s*(\d{1,2})\s*[:：]\s*(\d{2})(?:\s*[:：]\s*(\d{2}))?)?$"
)
CLOCK = re.compile(r"\d{1,2}:\d{2}")
EXTRA_TIME_FORMATS = ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d", "%Y%m%d", "%Y-%m-%d %H:%M")


# --------------------------------------------------------------------------- #
# time
# --------------------------------------------------------------------------- #


def probe_date_range(now: datetime) -> tuple[str, str]:
    """The ``page_time`` range to ask Baidu for: yesterday through today.

    Computed from the actual run time in ``APP_TIMEZONE`` so the filter follows
    the clock instead of a date pinned in the source. This is a *date* range,
    which is why the probe never calls it "the last 24 hours": it is the
    narrowest date window that can contain those 24 hours, and the precise check
    is local (:func:`is_within_last_24h`).
    """
    local = as_utc(now).astimezone(app_timezone())
    today = local.date()
    return (today - timedelta(days=1)).strftime(DATE_FORMAT), today.strftime(DATE_FORMAT)


@dataclass(frozen=True)
class PublishTime:
    """A publish timestamp as the response gave it.

    ``has_time`` is false for a bare date such as ``2026-09-19``: the date is
    known but the moment is not, and those are different answers. Without that
    flag a date-only result would look like a 00:00 publication and be judged
    against the 24h window on evidence the response never provided.
    """

    raw: str = ""
    moment: datetime | None = None
    has_time: bool = False


def parse_page_time(value: Any, tz: ZoneInfo | None = None) -> PublishTime:
    """Parse a publish time from the response, or report it as unknown.

    Accepted: ISO dates and timestamps (with or without a zone), the
    ``2026年09月19日`` form, and epoch seconds or milliseconds. A naive value is
    read in ``APP_TIMEZONE``, matching how the project treats wall-clock times
    from Chinese sources. Anything else - including relative strings such as
    ``3小时前`` - stays unknown and keeps its raw text so it can be reported
    rather than guessed at.
    """
    zone = tz or app_timezone()
    raw = "" if value is None else str(value).strip()
    if not raw:
        return PublishTime()

    number = _as_epoch_seconds(raw)
    if number is not None:
        try:
            moment = datetime.fromtimestamp(number, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return PublishTime(raw=raw)
        return PublishTime(raw=raw, moment=moment, has_time=True)

    if ISO_DATE_ONLY.match(raw):
        return PublishTime(raw=raw, moment=_attach(raw, zone), has_time=False)

    cjk = CJK_DATE.match(raw)
    if cjk:
        year, month, day, hour, minute, second = cjk.groups()
        moment = datetime(int(year), int(month), int(day), tzinfo=zone)
        if hour is not None:
            moment = moment.replace(hour=int(hour), minute=int(minute), second=int(second or 0))
        return PublishTime(raw=raw, moment=moment, has_time=hour is not None)

    normalized = raw.replace("：", ":").replace("Z", "+00:00")
    try:
        moment = datetime.fromisoformat(normalized)
    except ValueError:
        moment = _strptime_any(normalized)
    if moment is None:
        return PublishTime(raw=raw)

    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=zone)
    return PublishTime(raw=raw, moment=moment, has_time=bool(CLOCK.search(normalized)))


def _as_epoch_seconds(raw: str) -> float | None:
    """Epoch seconds or milliseconds, if ``raw`` is a plain number."""
    if not re.fullmatch(r"\d{9,14}", raw):
        return None
    number = float(raw)
    if len(raw) >= 13:
        number = number / 1000.0
    return number


def _attach(raw: str, zone: ZoneInfo) -> datetime | None:
    try:
        return datetime.strptime(raw, DATE_FORMAT).replace(tzinfo=zone)
    except ValueError:
        return None


def _strptime_any(raw: str) -> datetime | None:
    for pattern in EXTRA_TIME_FORMATS:
        try:
            return datetime.strptime(raw, pattern)
        except ValueError:
            continue
    return None


def is_within_last_24h(moment: datetime | None, now: datetime) -> bool:
    """Whether ``moment`` falls in the last 24 hours, future excluded.

    A future timestamp is never "recent": clock skew and pre-dated pages would
    otherwise pass the ``age <= 24h`` test. Reuses the project's ``is_future``
    for the same reason the digest window does.
    """
    if moment is None or is_future(moment, now):
        return False
    return as_utc(now) - as_utc(moment) <= timedelta(hours=24)


def format_publish_time(value: PublishTime) -> str:
    """One line for the terminal: the local time, its precision, or the excuse."""
    if value.moment is None:
        return f"(unparsed: {value.raw})" if value.raw else "(unknown)"
    local = as_utc(value.moment).astimezone(app_timezone())
    if not value.has_time:
        return f"{local.strftime(DATE_FORMAT)} (date only)"
    return local.strftime("%Y-%m-%d %H:%M %z")

# --------------------------------------------------------------------------- #
# domains
# --------------------------------------------------------------------------- #


def domain_of(url: str) -> str:
    """The hostname of ``url``, lowercased and without a leading ``www.``."""
    host = (urlsplit(str(url or "").strip()).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def known_source_domains(sources: Iterable[Any] = SOURCES) -> frozenset[str]:
    """The hostnames the fixed sources are read from."""
    return frozenset(domain for domain in (domain_of(source.url) for source in sources) if domain)


def is_known_source_domain(domain: str, known: frozenset[str]) -> bool:
    """Whether a result's hostname is already covered by a fixed source.

    The comparison is on hostnames, and it matches in both directions on a dot
    boundary: ``blog.openai.com`` counts as covered because ``openai.com`` is
    configured, and ``nvidia.com`` counts as covered because
    ``developer.nvidia.com`` is. That is intentionally the *conservative*
    direction - the question this probes is whether Baidu finds content outside
    the fixed sources, so a subdomain quirk must not be what makes a result look
    new.
    """
    if not domain:
        return False
    for candidate in known:
        if domain == candidate or domain.endswith(f".{candidate}") or candidate.endswith(f".{domain}"):
            return True
    return False


# --------------------------------------------------------------------------- #
# request and response
# --------------------------------------------------------------------------- #


def build_payload(query: str, start_date: str, end_date: str, *, top_k: int = DEFAULT_TOP_K) -> dict:
    """The request body for one query.

    ``sort.priority=auto`` is kept alongside the date filter because it is what
    lets the endpoint favour the freshest pages for these time-sensitive queries.
    """
    return {
        "messages": [{"role": "user", "content": query}],
        "search_source": SEARCH_SOURCE,
        "edition": EDITION,
        "resource_type_filter": [{"type": RESOURCE_TYPE, "top_k": top_k}],
        "search_filter": {"range": {"page_time": {"gte": start_date, "lte": end_date}}},
        "sort": {"priority": SORT_PRIORITY},
    }


@dataclass
class Attempt:
    """One HTTP call, however it ended."""

    status_code: int | None = None
    payload: Any = None
    raw_text: str = ""
    parsed: bool = True
    transport_error: str = ""

    @property
    def body_preview(self) -> str:
        text = self.raw_text.strip()
        if not text and self.payload is not None:
            text = json.dumps(self.payload, ensure_ascii=False)
        return text[:BODY_LIMIT] + ("..." if len(text) > BODY_LIMIT else "")


def send_request(url: str, headers: dict[str, str], payload: dict, timeout: float) -> Attempt:
    """Call the endpoint and never raise: every failure becomes an ``Attempt``.

    A broken transport is data for this probe, not an exception to abort on, and
    the cases it distinguishes - timeout, connection failure, other HTTP error,
    non-JSON body - are exactly the ones the report has to explain. No retry
    happens here: a 429 is reported, not hammered.
    """
    attempt = Attempt()
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException:
        attempt.transport_error = f"timed out after {timeout:g}s"
        return attempt
    except httpx.ConnectError as exc:
        attempt.transport_error = f"connection failed: {exc}"
        return attempt
    except httpx.HTTPError as exc:
        attempt.transport_error = f"HTTP error: {exc.__class__.__name__}"
        return attempt

    attempt.status_code = response.status_code
    attempt.raw_text = response.text
    try:
        attempt.payload = response.json()
    except ValueError:
        attempt.parsed = False
    return attempt


def error_message(payload: Any) -> str:
    """Baidu's error text, if the body carries one.

    Both error shapes this endpoint is known to use are read, plus the
    OpenAI-style one, and the numeric code is kept because it is what Baidu
    support asks for.
    """
    if not isinstance(payload, dict):
        return ""
    code = payload.get("error_code") or payload.get("code")
    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message") or error.get("msg") or error.get("code")
        if isinstance(message, str) and message.strip():
            return message.strip()
        return json.dumps(error, ensure_ascii=False)[:BODY_LIMIT]
    if isinstance(error, str) and error.strip():
        return error.strip()
    for key in ("error_msg", "message", "msg"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return f"{value.strip()} (code {code})" if code else value.strip()
    return ""


def top_level_keys(payload: Any) -> str:
    """The response's top-level keys, so a schema change is visible in the log."""
    if not isinstance(payload, dict):
        return "none (the body is not a JSON object)"
    keys = [str(key) for key in payload]
    shown = ", ".join(keys[:KEY_LIMIT])
    return shown + (", ..." if len(keys) > KEY_LIMIT else "")


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
        return f"HTTP {status}: Baidu failed{detail}"
    if status >= 400:
        return f"HTTP {status}: unexpected failure{detail}"
    if not attempt.parsed:
        return f"HTTP {status}: the body is not JSON, so no results could be read ({attempt.body_preview})"
    keys = top_level_keys(attempt.payload)
    return f"HTTP {status}: no results list in the response (top-level keys: {keys})"


@dataclass
class RawResult:
    """One entry from the result list, before anything is derived from it."""

    title: str = ""
    url: str = ""
    site: str = ""
    published: str = ""
    snippet: str = ""


@dataclass
class ParsedResponse:
    """What one response body yielded."""

    found: bool = False
    list_key: str = ""
    results: list[RawResult] = field(default_factory=list)
    skipped_no_url: int = 0


def _first_text(node: dict, keys: Sequence[str]) -> str:
    for key in keys:
        value = node.get(key)
        if isinstance(value, (str, int, float)) and str(value).strip():
            return str(value).strip()
    return ""


def find_result_list(payload: Any, *, _depth: int = 0) -> tuple[list[dict] | None, str]:
    """The web result entries and the key they were found under.

    ``None`` means "no result list here", which is a reading failure and is
    reported as one; an empty list means the query genuinely matched nothing.
    Those two must not collapse into the same report, or a schema change would
    silently look like a quiet news day.

    An empty list is a result list - the query matched nothing - and a list that
    holds at least one object is one too, so a stray non-object entry is skipped
    by :func:`parse_search_response` instead of invalidating the whole response.
    A list of plain strings is still rejected: under an ambiguous key such as
    ``data`` that would be a false positive.
    """
    if not isinstance(payload, dict) or _depth > 2:
        return None, ""
    for key in RESULT_LIST_KEYS:
        if key not in payload:
            continue
        value = payload[key]
        if isinstance(value, list) and (not value or any(isinstance(item, dict) for item in value)):
            return value, key
        if isinstance(value, dict):
            nested, path = find_result_list(value, _depth=_depth + 1)
            if nested is not None:
                return nested, f"{key}.{path}" if path else key
    return None, ""


def parse_search_response(payload: Any) -> ParsedResponse:
    """Read one response body into results.

    A missing field never sinks the response: an entry without a title keeps an
    empty title, an entry without a timestamp is reported as unknown. Only an
    entry with no URL at all is dropped - a URL is the entire point of a
    discovery probe - and the drop is counted so it stays visible.
    """
    parsed = ParsedResponse()
    nodes, key = find_result_list(payload)
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
            )
        )
    return parsed


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
    )


@dataclass
class Summary:
    """Every number the final report prints."""

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
    unique_results: list[SearchResult] = field(default_factory=list)
    irrelevant: list[SearchResult] = field(default_factory=list)

    @property
    def unique_urls(self) -> int:
        return len(self.unique_results)

    @property
    def unique_domains(self) -> int:
        return len(self.domains)


def summarize(outcomes: Sequence[QueryOutcome], now: datetime) -> Summary:
    """Count what the queries found. The same URL from two queries counts once.

    Deduplication reuses ``app.pipelines.urls.canonicalize_url`` so the probe and
    the pipeline agree on what "the same URL" means - a second set of canonical
    rules here would make the two disagree exactly where the answer matters.

    One caveat the counts cannot hide: a URL whose query string the canonicalizer
    keeps will count as a separate result even if it is the same article under a
    tracking variant the canonicalizer does not know. The duplicate count is
    therefore a lower bound.
    """
    summary = Summary(queries=len(outcomes))
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


def discovery_order(result: SearchResult, now: datetime) -> tuple:
    """Sort key for the discovered list: inside 24h first, then known times, then newest.

    Display ordering only. A result with no timestamp is not ranked last because
    it is worthless - it is ranked last because the probe cannot place it.
    """
    moment = result.page_time.moment
    inside = is_within_last_24h(moment, now) if result.page_time.has_time else False
    stamp = as_utc(moment).timestamp() if moment is not None else 0.0
    return (0 if inside else 1, 0 if moment is not None else 1, -stamp)


# --------------------------------------------------------------------------- #
# output
# --------------------------------------------------------------------------- #


def trim(text: str, limit: int) -> str:
    collapsed = " ".join(str(text or "").split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


def print_header(
    out: Callable[[str], None],
    query_count: int,
    configured: bool,
    start: str,
    end: str,
    timeout: float,
    top_k: int,
) -> None:
    out("Baidu Web Search Probe")
    out(f"Endpoint: {ENDPOINT}")
    out(f"Queries: {query_count}")
    out(f"API key: {'configured' if configured else 'missing'}")
    out(f"Page time range: {start} .. {end} (a date range, not a 24h guarantee)")
    out(f"Timeout: {timeout:g}s   top_k: {top_k}")
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
        out(f"   source: {result.site or result.domain or '(unknown)'}")
        out(f"   published: {format_publish_time(result.page_time)}")
        out(f"   url: {result.url}")
        out(f"   snippet: {trim(result.snippet, SNIPPET_LIMIT) or '(no snippet)'}")
        out("")


def print_summary(summary: Summary, out: Callable[[str], None]) -> None:
    out(LIST_SEPARATOR)
    out("SUMMARY")
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

def print_top_domains(summary: Summary, out: Callable[[str], None], limit: int = 15) -> None:
    out("")
    out("Top domains:")
    out(f"{'domain':<{DOMAIN_COLUMN}} count")
    out("-" * (DOMAIN_COLUMN + 6))
    for domain, count in summary.domains.most_common(limit):
        out(f"{domain:<{DOMAIN_COLUMN}} {count}")


def print_discovered(summary: Summary, now: datetime, out: Callable[[str], None]) -> None:
    discovered = [result for result in summary.unique_results if not result.known_source]
    discovered.sort(key=lambda result: discovery_order(result, now))

    out("")
    out(LIST_SEPARATOR)
    out("DISCOVERED CANDIDATES")
    out("")
    out("Hostnames the fixed sources do not cover, most recent first.")
    out("")
    if not discovered:
        if summary.unique_urls:
            out("(none - every hostname Baidu returned is already a configured source)")
        else:
            out("(no results to compare)")
        return
    for index, result in enumerate(discovered[:MAX_DISCOVERED_PRINTED], start=1):
        out(f"{index}. {trim(result.title, TITLE_LIMIT) or '(no title)'}")
        out(f"   source: {result.domain or '(unknown)'}")
        out(f"   published: {format_publish_time(result.page_time)}")
        out(f"   url: {result.url}")
        out("")


def print_relevance(summary: Summary, out: Callable[[str], None]) -> None:
    """Report results the project's own AI evidence rule would not accept.

    Reusing ``app.pipelines.ai_filter`` keeps the number reproducible instead of
    resting on a reviewer's mood. Read it as a hint: those word lists cover
    English terms and Chinese *brand* names, so a Chinese story that says 人工智能
    or 具身智能 without naming a model is flagged even when it is on topic.
    """
    out("")
    out(LIST_SEPARATOR)
    out("AI RELEVANCE (diagnostic)")
    out("")
    out(f"Unique results without AI evidence (app/pipelines/ai_filter): {len(summary.irrelevant)}")
    out("Hint only: those word lists are English plus Chinese brand names, so a Chinese")
    out("story about 人工智能 / 具身智能 with no model name is counted here as well.")
    for result in summary.irrelevant[:MAX_IRRELEVANT_SAMPLES]:
        out(f"  - {trim(result.title, TITLE_LIMIT) or '(no title)'} ({result.domain or 'no host'})")


def render_report(
    summary: Summary,
    now: datetime,
    out: Callable[[str], None],
) -> None:
    """The part of the report that can only be printed once every query is in.

    Per-query output is *not* repeated here: it is already printed as each query
    finishes, so a slow or rate-limited run still shows progress instead of
    staying silent until the end.
    """
    print_summary(summary, out)
    print_top_domains(summary, out)
    print_discovered(summary, now, out)
    print_relevance(summary, out)


# --------------------------------------------------------------------------- #
# entry points
# --------------------------------------------------------------------------- #


def api_key_from_env() -> str:
    return os.getenv("BAIDU_SEARCH_API_KEY", "").strip()


def check_query(query: str, max_chars: int) -> str:
    """The reason a query must not be sent, or an empty string.

    A too-long query is a known-bad request, so it is reported and skipped before
    it costs quota. Everything else the endpoint rejects comes back as a normal
    failure on that query alone.
    """
    if len(query) > max_chars:
        return (
            f"query is {len(query)} characters, over the {max_chars} character limit "
            "(local guard; raise it with --max-query-chars if the endpoint accepts more)"
        )
    return ""


def run(
    *,
    api_key: str,
    queries: Sequence[str] = QUERY_POOL,
    endpoint: str = ENDPOINT,
    timeout: float = DEFAULT_TIMEOUT,
    top_k: int = DEFAULT_TOP_K,
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

    print_header(out, len(queries), bool(api_key), start_date, end_date, timeout, top_k)

    outcomes: list[QueryOutcome] = []
    for query in queries:
        outcome = QueryOutcome(query=query)
        skip_reason = check_query(query, max_query_chars)
        if skip_reason:
            outcome.skipped = skip_reason
            outcomes.append(outcome)
            print_query_outcome(outcome, out)
            continue

        payload = build_payload(query, start_date, end_date, top_k=top_k)
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

    summary = summarize(outcomes, started)
    render_report(summary, started, out)
    return 0 if summary.successful else UNUSABLE_EXIT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Probe the Baidu AI Search Web Search API as a discovery layer for AI Daily"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"seconds to wait for each response (default: {DEFAULT_TIMEOUT:g})",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=DEFAULT_TOP_K,
        help=f"web results to request per query (default: {DEFAULT_TOP_K})",
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
        print("Baidu Web Search Probe")
        print(f"Endpoint: {ENDPOINT}")
        print()
        print("Missing environment variable: BAIDU_SEARCH_API_KEY")
        print("Set it in backend/.env (copy backend/.env.example) or in the environment.")
        return MISSING_CONFIG_EXIT

    if not args.dump_json:
        return run(
            api_key=api_key,
            timeout=args.timeout,
            top_k=args.top_k,
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
        timeout=args.timeout,
        top_k=args.top_k,
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