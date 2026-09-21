"""The Tavily Search request, used by the Web Discovery layer.

One job: ask Tavily's Search API one question and hand back the pages it named,
without deciding anything about them. Which candidates are worth keeping is
``app/services/web_discovery.py``'s business, and this module never imports it —
the collector knows about HTTP and the response schema, nothing else.

The parameters are the ones the Phase 10.15 benchmark validated, so a production
run is directly comparable with the numbers the decision was made on:

* ``topic=news`` restricts the corpus to news pages and turns
  ``include_published_date`` on, which is the field recency is measured from.
* ``time_range=day`` is Tavily's own name for the last 24 hours, and it is the
  replacement for the older ``days`` parameter — ``days`` no longer appears
  anywhere in Tavily's published API reference.
* ``search_depth=basic`` is the cheapest depth. The product needs candidate URLs
  and has its own article extractor, so paying for a provider to pre-process page
  text would buy nothing.
* ``include_answer``, ``include_raw_content`` and ``include_images`` stay off for
  the same reason and because each is billed.

Nothing here retries. A 429 is reported and the caller moves on: discovery is an
addition to the digest, never a reason to hold up a refresh.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any, Mapping, Sequence

import httpx

from app.collectors.http import USER_AGENT

ENDPOINT = "https://api.tavily.com/search"
TOPIC = "news"
SEARCH_DEPTH = "basic"
TIME_RANGE = "day"

# Only what is needed to discover a URL. ``include_published_date`` is requested
# explicitly even though ``topic=news`` already implies it, so the field the
# recency gate depends on cannot silently disappear if that default changes.
OPTIONS: Mapping[str, Any] = {
    "include_answer": False,
    "include_raw_content": False,
    "include_images": False,
    "include_published_date": True,
}

# Response field names, most likely first. The schema is not ours, so every read
# goes through a list and a missing field degrades to an empty value instead of
# dropping the response.
TITLE_KEYS = ("title",)
URL_KEYS = ("url", "link")
PUBLISHED_KEYS = ("published_date", "published_at", "publishedDate", "date")
SNIPPET_KEYS = ("content", "snippet", "description")
SCORE_KEYS = ("score", "relevance_score")

RESULT_LIST_KEYS = ("results", "data", "items", "documents")

BODY_LIMIT = 300
KEY_LIMIT = 12


@dataclass
class Attempt:
    """One HTTP call, however it ended. Never an exception."""

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


@dataclass
class TavilyHit:
    """One entry from ``results``, before anything is decided about it."""

    title: str = ""
    url: str = ""
    published: str = ""
    snippet: str = ""
    score: str = ""


@dataclass
class ParsedResponse:
    """What one response body yielded."""

    found: bool = False
    list_key: str = ""
    hits: list[TavilyHit] = field(default_factory=list)
    skipped_no_url: int = 0


def build_payload(query: str, *, max_results: int) -> dict:
    """The request body for one query.

    No ``exclude_domains``: filtering is not this layer's job. Portals and
    aggregators are judged by importance, media selection and ranking downstream,
    and a discovery layer that maintained its own blacklist would be a second,
    worse source configuration.
    """
    payload: dict[str, Any] = {
        "query": query,
        "topic": TOPIC,
        "search_depth": SEARCH_DEPTH,
        "time_range": TIME_RANGE,
        "max_results": max_results,
    }
    payload.update(OPTIONS)
    return payload


def send_request(
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, Any],
    timeout: float,
) -> Attempt:
    """Call the endpoint and never raise: every failure becomes an ``Attempt``.

    The cases it distinguishes — timeout, connection failure, HTTP error,
    non-JSON body — are exactly the ones the refresh log has to explain, and a
    broken transport is data for this layer rather than an exception to abort on.
    """
    attempt = Attempt()
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.post(url, headers=dict(headers), json=dict(payload))
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


def auth_headers(api_key: str) -> dict[str, str]:
    """The headers for one request. The key is never logged by this module."""
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }


def normalize_published(raw: Any) -> str:
    """Tavily's date encoding translated into an ISO 8601 string.

    Tavily answers with an RFC 2822 timestamp (``Sun, 20 Sep 2026 14:00:00 GMT``,
    sometimes ``null``). Rather than give discovery its own date parsing, the wire
    value is converted here and then handed to the same
    :func:`app.services.digest_window.parse_timestamp` the rest of the pipeline
    uses, so which formats are accepted and how precision is treated stay one
    rule. Anything the conversion does not recognise — including ``null`` and an
    empty string — is passed through untouched, so the caller reports it as
    unknown instead of this function inventing a date.
    """
    text = "" if raw is None else str(raw).strip()
    if not text:
        return ""
    try:
        moment = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        return text
    if moment is None:
        return text
    return moment.isoformat()


def published_at(raw: Any) -> datetime | None:
    """A hit's publish time as an aware datetime, or ``None`` when unknown."""
    from app.services.digest_window import parse_timestamp

    return parse_timestamp(normalize_published(raw))


def _first_text(node: Mapping[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        value = node.get(key)
        # ``score`` arrives as a number, and a bool is not a number here.
        if isinstance(value, bool):
            continue
        if isinstance(value, (str, int, float)) and str(value).strip():
            return str(value).strip()
    return ""


def find_result_list(payload: Any, *, _depth: int = 0) -> tuple[list | None, str]:
    """The ``results`` list and the key it was found under.

    ``None`` means "no item list here", which is a schema change and is reported
    as one; an empty list means the query genuinely matched nothing. Those two
    must not collapse into the same answer, or a renamed field would look like a
    quiet news day.
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
    """Read one response body into hits.

    A missing field never sinks the response: a hit without a title keeps an empty
    title, one without ``published_date`` is reported as unknown downstream. Only
    a hit with no address at all is dropped — a URL is the entire point of a
    discovery request — and the drop is counted so it stays visible.
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
        parsed.hits.append(
            TavilyHit(
                title=_first_text(node, TITLE_KEYS),
                url=url,
                published=_first_text(node, PUBLISHED_KEYS),
                snippet=_first_text(node, SNIPPET_KEYS),
                score=_first_text(node, SCORE_KEYS),
            )
        )
    return parsed


def error_message(payload: Any) -> str:
    """Tavily's error text, if the body carries one.

    Verified against the live endpoint: a rejected key answers 401 with
    ``{"detail": {"error": "..."}}``, a bad parameter answers 400 with the same
    shape, and a missing required field answers 422 with FastAPI's
    ``detail: [{loc, msg}]`` list.
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


def top_level_keys(payload: Any) -> str:
    """The response's top-level keys, so a schema change is visible in the log."""
    if not isinstance(payload, dict):
        return "none (the body is not a JSON object)"
    keys = [str(key) for key in payload]
    return ", ".join(keys[:KEY_LIMIT]) + (", ..." if len(keys) > KEY_LIMIT else "")


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
        return f"HTTP 429: rate limited, and discovery does not retry{detail}"
    if status in (400, 422):
        return f"HTTP {status}: the request was rejected{detail}"
    if status in (432, 433):
        return f"HTTP {status}: the plan's usage limit was reached{detail}"
    if status >= 500:
        return f"HTTP {status}: Tavily failed{detail}"
    if status >= 400:
        return f"HTTP {status}: unexpected failure{detail}"
    if not attempt.parsed:
        return f"HTTP {status}: the body is not JSON, so no results could be read"
    return f"HTTP {status}: no results list in the response (top-level keys: {top_level_keys(attempt.payload)})"