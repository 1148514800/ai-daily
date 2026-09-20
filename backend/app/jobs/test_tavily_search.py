"""Can Tavily Web Search be the dynamic discovery layer for AI Daily?

    cd backend
    uv run python -m app.jobs.test_tavily_search

The third probe in the Phase 10.15 series, after ``test_baidu_search`` and
``test_aliyun_search``. It asks the same question the other two ask - *can this
engine find valuable AI pages that the fixed sources in ``app/config/sources.py``
do not already cover?* - over the same ten queries, so the three engines can be
compared row by row.

It calls the official Tavily Search endpoint ``POST https://api.tavily.com/search``
with ``Authorization: Bearer`` (the scheme in Tavily's current OpenAPI document)
and asks for pages only: ``include_answer``, ``include_raw_content`` and
``include_images`` all stay off, so the response is result metadata rather than a
generated answer or a copy of somebody else's article text. AI Daily has its own
article extractor; a search provider must not do that work for us.

Anything that would make the comparison unfair is shared with the other probes by
import rather than re-implemented - the query pool, the publish-time type and
formatter, the "last 24 hours" rule, URL canonicalization, the known-fixed-source
test, the top-domain table and the six source-quality buckets all come from
``test_baidu_search`` and ``test_aliyun_search``. A second copy of those rules
would drift, and a drifting copy is exactly what a comparison cannot survive.

Two things are provider-specific and therefore live here:

* **the request shape.** Tavily has no ``page_time`` range and no
  ``advancedParams`` map; it takes ``topic``, ``search_depth``,
  ``time_range`` and ``max_results``. Note that ``time_range`` is used rather
  than the older ``days`` parameter: ``days`` no longer appears anywhere in
  Tavily's published API reference (checked against
  ``docs.tavily.com/documentation/api-reference/endpoint/search.md``), so the
  documented ``time_range="day"`` is what this probe sends.
* **the date format.** Tavily returns ``published_date`` as an RFC 2822
  timestamp (``Sun, 20 Sep 2026 14:00:00 GMT``), which the shared parser does
  not read. It is normalised to ISO 8601 and then handed to the shared
  ``parse_page_time``, so *which* formats count and how precision is treated
  stay one rule; only the wire encoding is translated.

Nothing is integrated. No database, schema, collector, refresh pipeline,
scheduler, source configuration or LLM client is touched, and a search result is
never written anywhere: the flow is Tavily Search -> candidate URLs -> printed
counts. Results are not news.

The API key is read from ``TAVILY_API_KEY`` and is never printed, logged or
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
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Mapping, Sequence

from app.collectors.http import USER_AGENT
from app.config.env import load_dotenv
from app.pipelines.ai_filter import is_ai_related
from app.pipelines.urls import canonicalize_url
from app.services.digest_window import as_utc

# Shared with the Baidu and Aliyun probes on purpose: identical conditions are the
# whole point of running three engines. See the module docstring.
from app.jobs.test_baidu_search import (
    BODY_LIMIT,
    DEFAULT_MAX_QUERY_CHARS,
    DOMAIN_COLUMN,
    LIST_SEPARATOR,
    MAX_IRRELEVANT_SAMPLES,
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
    send_request,
    top_level_keys,
    trim,
)

# The six quality buckets are the Aliyun probe's probe-local taxonomy, imported so
# the three engines are described with one vocabulary. They are a *description*
# used to compare engines, not something the product uses: ``source_type`` in
# app/config/sources.py stays the only classification business code may read.
from app.jobs.test_aliyun_search import (
    SECOND_HAND_DOMAINS,
    SOURCE_QUALITY_ORDER,
    UNKNOWN_QUALITY,
    classify_source,
    watched_domain_of,
)

ENDPOINT = "https://api.tavily.com/search"

# Round one uses ``basic``. The task is to *discover* candidate URLs: AI Daily
# already extracts article bodies itself, so ``advanced`` would buy deeper page
# processing the product does not need, at twice the credits. ``fast`` and
# ``ultra-fast`` go the other way and trade recall for latency, which is the one
# thing a discovery probe must not do.
SEARCH_DEPTH = "basic"

# ``news`` restricts the corpus to news pages and - per the reference - turns
# ``include_published_date`` on automatically, which is the field this probe
# measures recency with. ``general`` would mix in documentation, product pages
# and social posts, a different question than "what was published recently".
TOPIC = "news"

# The documented relative window, and the replacement for the retired ``days``
# parameter: "day" is Tavily's own name for the last 24 hours. It is a *relative*
# window that follows the clock, so no date is pinned in the source.
TIME_RANGE = "day"

# What ``time_range`` means in Tavily's own words. Printed in the header so the
# report never implies the request asked for an exact rolling window: the precise
# check is local (see ``is_within_last_24h``).
TIME_RANGE_NOTE = 'Tavily "day" = the last 24 hours, relative to the request'

# 10 matches the other two probes so all three are asked for the same amount of
# material: 10 queries x 10 results = 100 raw results.
DEFAULT_MAX_RESULTS = 10

# Tavily documents 20 as the maximum for one request. A larger value is not sent:
# asking for more than the API allows would only produce a request that cannot be
# answered as written.
MAX_RESULTS_LIMIT = 20

# Discovery only. ``include_answer`` would add an LLM-written answer, and
# ``include_raw_content`` a copy of the page text - both are extra billed work
# that a discovery probe must not pay for, and neither is a discovery signal.
# ``include_published_date`` is requested explicitly even though ``topic=news``
# already implies it, so the field the recency metric depends on does not
# silently disappear if that default ever changes.
CONTENTS = {
    "include_answer": False,
    "include_raw_content": False,
    "include_images": False,
    "include_published_date": True,
}

# Asking for the credit count costs nothing and makes the one real run's spend
# verifiable instead of estimated. The response carries ``usage: {credits: N}``.
INCLUDE_USAGE = True

DEFAULT_TIMEOUT = 30.0

# The required report prints the ten most valuable discoveries, not every one.
TOP_DISCOVERED_PRINTED = 10

# --- result field names ---------------------------------------------------- #
#
# Taken from Tavily's current response schema: ``title``, ``url``, ``content``,
# ``score``, ``published_date``, ``id``. The alternates are tolerated so a
# rename shows up as an empty field on one result rather than a crash, and every
# read is tolerant: a missing field never drops the response.
TITLE_KEYS = ("title",)
URL_KEYS = ("url", "link")
PUBLISHED_KEYS = ("published_date", "published_at", "publishedDate", "date")
SNIPPET_KEYS = ("content", "snippet", "description")
SCORE_KEYS = ("score", "relevance_score", "rerank_score")

# The result list. ``results`` is what the endpoint returns; the rest are
# tolerated so a rename is reported as "no result list" instead of a crash.
RESULT_LIST_KEYS = ("results", "data", "items", "documents")

# Tavily sends no per-result tags. The map is kept as an empty field so the
# report shape matches the other two probes, and so a future ``tags`` field
# would be picked up without changing the parser.
TAG_KEYS = ("tags",)
GENRE_KEY = "genre"

# --------------------------------------------------------------------------- #
# request payload
# --------------------------------------------------------------------------- #


def build_payload(
    query: str,
    *,
    max_results: int = DEFAULT_MAX_RESULTS,
    topic: str = TOPIC,
    search_depth: str = SEARCH_DEPTH,
    time_range: str = TIME_RANGE,
) -> dict:
    """The request body for one query, as Tavily's reference defines it.

    ``time_range="day"`` carries the recency filter, so no date is computed
    here and none is pinned in the source. It is a relative window, which is why
    the probe still verifies every timestamp locally: ``day`` is what Tavily
    promises, not what the pages necessarily say.

    ``exclude_domains`` is the documented lever for the second-hand watchlist and
    is deliberately unused, for the same reason the other two probes leave their
    exclusion list empty: this round has to show the raw recall, or the
    comparison would be measuring the blacklist instead of the engine.
    """
    payload: dict[str, Any] = {
        "query": query,
        "topic": topic,
        "search_depth": search_depth,
        "time_range": time_range,
        "max_results": max_results,
    }
    payload.update(CONTENTS)
    if INCLUDE_USAGE:
        payload["include_usage"] = True
    return payload


def usage_credits(payload: Any) -> int:
    """The credits one response reported, or 0 when it did not say.

    Read for the report only. The probe never calls ``/usage`` and never guesses:
    a response without ``usage`` simply contributes nothing to the total.
    """
    if not isinstance(payload, Mapping):
        return 0
    usage = payload.get("usage")
    if not isinstance(usage, Mapping):
        return 0
    credits = usage.get("credits")
    if isinstance(credits, bool):
        return 0
    if isinstance(credits, (int, float)):
        return int(credits)
    return 0
# --------------------------------------------------------------------------- #
# response parsing
# --------------------------------------------------------------------------- #


@dataclass
class RawResult:
    """One entry from ``results``, before anything is derived from it."""

    title: str = ""
    url: str = ""
    published: str = ""
    snippet: str = ""
    score: str = ""
    tags: dict[str, str] = field(default_factory=dict)


@dataclass
class ParsedResponse:
    """What one response body yielded."""

    found: bool = False
    list_key: str = ""
    results: list[RawResult] = field(default_factory=list)
    skipped_no_url: int = 0
    credits: int = 0


def normalize_published(raw: str) -> str:
    """Tavily's date encoding translated into the shared parser's input.

    Tavily answers with an RFC 2822 timestamp (``Sun, 20 Sep 2026 14:00:00 GMT``,
    sometimes ``null``), while the shared :func:`parse_page_time` accepts ISO 8601,
    the ``2026年09月19日`` form and epoch numbers. Rather than teach a third probe
    its own date parsing, the wire value is converted here and then parsed by the
    shared rule, so *which* formats count, how a bare date is treated and how
    precision is reported stay one implementation for all three probes.

    Anything the conversion does not recognise - including ``null`` and an empty
    string - is passed through untouched, so the shared parser reports it as
    unknown rather than this function inventing a date.
    """
    text = "" if raw is None else str(raw).strip()
    if not text:
        return ""
    try:
        moment = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return text
    if moment is None:
        return text
    return moment.isoformat()


def _first_text(node: Mapping[str, Any], keys: Sequence[str]) -> str:
    """The first non-empty scalar under ``keys``, as text.

    ``score`` arrives as a number, so ints and floats are accepted and stringified
    here rather than being stringified later at the printing site.
    """
    for key in keys:
        value = node.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (str, int, float)) and str(value).strip():
            return str(value).strip()
    return ""


def find_result_list(payload: Any, *, _depth: int = 0) -> tuple[list | None, str]:
    """The ``results`` list and the key it was found under.

    ``None`` means "no item list here", which is a reading failure and is
    reported as one; an empty list means the query genuinely matched nothing.
    Those two must not collapse into the same report, or a schema change would
    silently look like a quiet news day.
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
    empty title, an entry without ``published_date`` is reported as unknown, and
    an entry without a score keeps an empty score. Only an entry with no address
    at all is dropped - a URL is the entire point of a discovery probe - and the
    drop is counted so it stays visible.
    """
    parsed = ParsedResponse()
    nodes, key = find_result_list(payload)
    if nodes is None:
        return parsed

    parsed.found = True
    parsed.list_key = key
    parsed.credits = usage_credits(payload)
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
                published=_first_text(node, PUBLISHED_KEYS),
                snippet=_first_text(node, SNIPPET_KEYS),
                score=_first_text(node, SCORE_KEYS),
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


def _as_text(value: Any) -> str:
    """A tag value flattened to text, tolerating numbers and booleans."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value).strip()
    return ""


def normalize_tags(value: Any) -> dict[str, str]:
    """The ``tags`` map flattened to text, with unknown keys kept.

    Tavily returns no tags today, so this is normally empty. The other two probes
    keep a tag map because their engines publish one, and keeping the same shape
    here means the report, the counters and the ``tags.genre`` diagnostic line do
    not have to be special-cased for the engine that happens to have none. A tag
    that does appear is shown and never filtered, because a value the probe does
    not recognise is evidence of a schema change, not something to hide.
    """
    if not isinstance(value, Mapping):
        return {}
    tags: dict[str, str] = {}
    for key, raw in value.items():
        text = _as_text(raw)
        if text:
            tags[str(key)] = text
    return tags


def tag_of(tags: Mapping[str, str], key: str) -> str:
    """One tag value, case-insensitively matched on the key."""
    wanted = key.lower()
    for name, value in tags.items():
        if name.lower() == wanted:
            return value
    return ""


def format_tags(tags: Mapping[str, str]) -> str:
    """A compact one-line rendering of the tags for the terminal."""
    if not tags:
        return "(none)"
    return " ".join(f"{key}={value}" for key, value in sorted(tags.items()))


def error_message(payload: Any) -> str:
    """Tavily's error text, if the body carries one.

    Verified against the live endpoint: an invalid key answers HTTP 401 with
    ``{"detail": {"error": "Unauthorized: missing or invalid API key."}}``, a bad
    parameter answers 400 with the same ``detail.error`` shape, and a missing
    required field answers 422 with FastAPI's ``detail: [{loc, msg}]`` list. All
    three are read here so the report quotes the service instead of the status
    code alone.
    """
    if not isinstance(payload, dict):
        return ""
    detail = payload.get("detail")
    if isinstance(detail, dict):
        message = detail.get("error") or detail.get("message") or detail.get("msg")
        if isinstance(message, str) and message.strip():
            return message.strip()
        if detail:
            return json.dumps(detail, ensure_ascii=False)[:BODY_LIMIT]
    if isinstance(detail, list):
        parts: list[str] = []
        for entry in detail[:3]:
            if isinstance(entry, dict):
                location = ".".join(str(part) for part in entry.get("loc", ()) if part != "body")
                message = entry.get("msg") or entry.get("type") or ""
                parts.append(f"{location}: {message}".strip(": ") if location else str(message))
        if parts:
            return "; ".join(parts)
        return json.dumps(detail, ensure_ascii=False)[:BODY_LIMIT]
    if isinstance(detail, str) and detail.strip():
        return detail.strip()
    for key in ("error", "message", "msg"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
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
    if status in (400, 422):
        return f"HTTP {status}: the request was rejected{detail}"
    if status in (432, 433):
        return f"HTTP {status}: the plan's usage limit was reached{detail}"
    if status >= 500:
        return f"HTTP {status}: Tavily failed{detail}"
    if status >= 400:
        return f"HTTP {status}: unexpected failure{detail}"
    if not attempt.parsed:
        return f"HTTP {status}: the body is not JSON, so no results could be read ({attempt.body_preview})"
    keys = top_level_keys(attempt.payload)
    return f"HTTP {status}: no results list in the response (top-level keys: {keys})"


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
    snippet: str = ""
    page_time: PublishTime = field(default_factory=PublishTime)
    known_source: bool = False
    score: str = ""
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
    credits: int = 0

    @property
    def status_code(self) -> int | None:
        return self.attempt.status_code if self.attempt else None


def to_search_result(raw: RawResult, query: str, known: frozenset[str]) -> SearchResult:
    """Derive everything the report needs from one raw entry.

    The domain always comes from ``url``, never from anything the provider calls a
    site name. The Aliyun probe had to learn this the hard way - CleverSee's
    ``hostname`` is a display name such as "云栖大会", and reading it as a hostname
    silently corrupts every downstream count. Tavily sends no site name at all,
    but the rule is kept identical so all three engines are counted the same way.
    """
    domain = domain_of(raw.url)
    return SearchResult(
        query=query,
        title=raw.title,
        url=raw.url,
        canonical_url=canonicalize_url(raw.url),
        domain=domain,
        snippet=raw.snippet,
        page_time=parse_page_time(normalize_published(raw.published)),
        known_source=is_known_source_domain(domain, known),
        score=raw.score,
        tags=raw.tags,
        quality=classify_source(domain, known=known),
    )


@dataclass
class Summary:
    """Every number the final report prints."""

    topic: str = TOPIC
    search_depth: str = SEARCH_DEPTH
    time_range: str = TIME_RANGE
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
    credits: int = 0
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


def summarize(
    outcomes: Sequence[QueryOutcome],
    now: datetime,
    *,
    topic: str = TOPIC,
    search_depth: str = SEARCH_DEPTH,
    time_range: str = TIME_RANGE,
) -> Summary:
    """Count what the queries found. The same URL from two queries counts once.

    Deduplication, the recency buckets and the known-source split are the same
    rules the Baidu and Aliyun probes use (``canonicalize_url``,
    ``is_within_last_24h``, ``is_known_source_domain``, ``classify_source``), so
    all three summaries are directly comparable. The duplicate count is a lower
    bound: canonicalization only removes the tracking parameters the project
    already knows about.
    """
    summary = Summary(topic=topic, search_depth=search_depth, time_range=time_range, queries=len(outcomes))
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
        summary.credits += outcome.credits
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
    """Discovery order, with Tavily's own relevance score as the tie-break.

    ``discovery_order`` from the Baidu probe decides first (inside 24h, then known
    times, then newest), so all three probes list candidates in the same order.
    Only results that tie on all of that are separated by the provider's score,
    which is engine-specific and therefore must not outrank the shared rules.
    """
    return (*discovery_order(result, now), -score_as_float(result.score))


def score_as_float(value: str) -> float:
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
    timeout: float,
    max_results: int,
    *,
    topic: str = TOPIC,
    search_depth: str = SEARCH_DEPTH,
    time_range: str = TIME_RANGE,
) -> None:
    out("Tavily Web Search Probe")
    out(f"Endpoint: {ENDPOINT}")
    out(f"Queries: {query_count}")
    out(f"API key: {'configured' if configured else 'missing'}")
    out(f"Topic: {topic}   Days window: {time_range}   Search depth: {search_depth}")
    out(f"Recency: {TIME_RANGE_NOTE} (a window, not a per-result guarantee)")
    out(f"Timeout: {timeout:g}s   max_results: {max_results}")
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
        out(f"   published_at: {format_publish_time(result.page_time)}")
        out(f"   score: {result.score or '(none)'}")
        out(f"   tags: {format_tags(result.tags)}")
        out(f"   url: {result.url}")
        out(f"   snippet: {trim(result.snippet, SNIPPET_LIMIT) or '(no snippet)'}")
        out("")


def print_summary(summary: Summary, out: Callable[[str], None]) -> None:
    out(LIST_SEPARATOR)
    out("SUMMARY")
    out("")
    out("Provider: Tavily")
    out(f"Topic: {summary.topic}")
    out(f"Days: 1 (requested as time_range={summary.time_range})")
    out(f"Search depth: {summary.search_depth}")
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
    out("")
    out(f"Credits reported by the API: {summary.credits}")


def print_source_quality(summary: Summary, out: Callable[[str], None]) -> None:
    """The buckets, the second-hand watchlist and any tags the engine sent.

    Reported in ``SOURCE_QUALITY_ORDER`` rather than by count, so three runs (or
    three engines) line up row for row.
    """
    out("")
    out(LIST_SEPARATOR)
    out("SOURCE QUALITY (probe analysis only)")
    out("")
    out("Probe-local buckets, shared with the Aliyun probe. Nothing here writes to")
    out("app/config/sources.py and no business rule may depend on these names.")
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


def print_candidates(summary: Summary, now: datetime, out: Callable[[str], None]) -> None:
    """The ten most valuable new URLs, chosen deterministically.

    Ranking is pure code - inside the last 24 hours first, then newest, then the
    engine's own score - and never a model's opinion of the page. Only hostnames
    the fixed sources do not cover are eligible, because the question this probe
    exists to answer is what Tavily finds *beyond* the sources we already read.
    """
    discovered = [result for result in summary.unique_results if not result.known_source]
    discovered.sort(key=lambda result: candidate_order(result, now))

    out("")
    out(LIST_SEPARATOR)
    out(f"TOP {TOP_DISCOVERED_PRINTED} VALUABLE DISCOVERED RESULTS")
    out("")
    out("Hostnames the fixed sources do not cover; inside the last 24h first, then")
    out("newest, then the engine's own score. Deterministic ordering, no LLM.")
    out("")
    if not discovered:
        if summary.unique_urls:
            out("(none - every hostname Tavily returned is already a configured source)")
        else:
            out("(no results to compare)")
        return
    for index, result in enumerate(discovered[:TOP_DISCOVERED_PRINTED], start=1):
        out(f"{index}. {trim(result.title, TITLE_LIMIT) or '(no title)'}")
        out(f"   domain: {result.domain or '(unknown)'}")
        out(f"   published_at: {format_publish_time(result.page_time)}")
        out(f"   score: {result.score or '(none)'}")
        out(f"   tags: {format_tags(result.tags)}")
        out(f"   url: {result.url}")
        out("")


def print_relevance(summary: Summary, out: Callable[[str], None]) -> None:
    """Results the project's own AI evidence rule would not accept.

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
    return os.getenv("TAVILY_API_KEY", "").strip()


def run(
    *,
    api_key: str,
    queries: Sequence[str] = QUERY_POOL,
    endpoint: str = ENDPOINT,
    topic: str = TOPIC,
    search_depth: str = SEARCH_DEPTH,
    time_range: str = TIME_RANGE,
    timeout: float = DEFAULT_TIMEOUT,
    max_results: int = DEFAULT_MAX_RESULTS,
    max_query_chars: int = DEFAULT_MAX_QUERY_CHARS,
    now: datetime | None = None,
    send: Callable[[str, dict, dict, float], Attempt] | None = None,
    out: Callable[[str], None] = print,
) -> int:
    """Run every query and print the report. Returns the exit status.

    One query failing never stops the next one: discovery is being measured, and
    dropping nine queries because the first hit a 429 would produce a report about
    nothing - and, with a metered API, would also waste the credits already spent.
    """
    transport = send or send_request
    started = as_utc(now or datetime.now(timezone.utc))
    known = known_source_domains()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }

    print_header(
        out,
        len(queries),
        bool(api_key),
        timeout,
        max_results,
        topic=topic,
        search_depth=search_depth,
        time_range=time_range,
    )

    outcomes: list[QueryOutcome] = []
    for query in queries:
        outcome = QueryOutcome(query=query)
        skip_reason = check_query(query, max_query_chars)
        if skip_reason:
            outcome.skipped = skip_reason
            outcomes.append(outcome)
            print_query_outcome(outcome, out)
            continue

        payload = build_payload(
            query,
            max_results=max_results,
            topic=topic,
            search_depth=search_depth,
            time_range=time_range,
        )
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
                outcome.credits = parsed.credits
                outcome.results = [to_search_result(raw, query, known) for raw in parsed.results]

        outcomes.append(outcome)
        print_query_outcome(outcome, out)

    summary = summarize(outcomes, started, topic=topic, search_depth=search_depth, time_range=time_range)
    render_report(summary, started, out)
    return 0 if summary.successful else UNUSABLE_EXIT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Probe the Tavily Search API as a discovery layer for AI Daily"
    )
    parser.add_argument(
        "--topic",
        default=TOPIC,
        choices=("news", "general", "finance"),
        help=f"Tavily topic (round one tests only {TOPIC})",
    )
    parser.add_argument(
        "--search-depth",
        default=SEARCH_DEPTH,
        help=f"Tavily search_depth (round one tests only {SEARCH_DEPTH})",
    )
    parser.add_argument(
        "--time-range",
        default=TIME_RANGE,
        choices=("day", "week", "month", "year"),
        help=f"Tavily time_range, the documented replacement for 'days' (default: {TIME_RANGE})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"seconds to wait for each response (default: {DEFAULT_TIMEOUT:g})",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=DEFAULT_MAX_RESULTS,
        help=f"results to request per query (default: {DEFAULT_MAX_RESULTS}, max {MAX_RESULTS_LIMIT})",
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
        print("Tavily Web Search Probe")
        print(f"Endpoint: {ENDPOINT}")
        print(f"Topic: {args.topic}   Search depth: {args.search_depth}")
        print()
        print("Missing environment variable: TAVILY_API_KEY")
        print("Set it in backend/.env (copy backend/.env.example) or in the environment.")
        return MISSING_CONFIG_EXIT

    if args.max_results > MAX_RESULTS_LIMIT:
        print(f"max_results is {args.max_results}; Tavily documents at most {MAX_RESULTS_LIMIT} per request.")
        print(f"Nothing was sent. Lower it to {MAX_RESULTS_LIMIT} or less.")
        return MISSING_CONFIG_EXIT

    if not args.dump_json:
        return run(
            api_key=api_key,
            topic=args.topic,
            search_depth=args.search_depth,
            time_range=args.time_range,
            timeout=args.timeout,
            max_results=args.max_results,
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
        topic=args.topic,
        search_depth=args.search_depth,
        time_range=args.time_range,
        timeout=args.timeout,
        max_results=args.max_results,
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