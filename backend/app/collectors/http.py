"""Shared HTTP fetching for the news collectors and the article extractor."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

USER_AGENT = "ai-daily/0.1 (+https://github.com/1148514800/ai-daily)"
DEFAULT_TIMEOUT = 10.0
# A page that needs more than a handful of hops is a redirect trap, not an
# article, so extraction gives up instead of following it forever.
MAX_REDIRECTS = 5
RSS_ACCEPT = "application/rss+xml, application/atom+xml, application/xml, text/xml"
HTML_ACCEPT = "text/html,application/xhtml+xml"


class FetchError(Exception):
    """A page could not be retrieved. Carries the status when there was one."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class FetchResult:
    """A retrieved document plus the metadata extraction needs to judge it.

    ``fetch_text`` deliberately returns a bare string because the feed readers
    only care about the body. The article extractor has to distinguish "no such
    page" from "not HTML" from "empty body", so it reads this instead.
    """

    url: str
    status: int
    content_type: str
    text: str


def fetch_text(url: str, *, timeout: float = DEFAULT_TIMEOUT, accept: str = HTML_ACCEPT) -> str:
    headers = {"User-Agent": USER_AGENT, "Accept": accept}
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.text


def fetch_document(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    accept: str = HTML_ACCEPT,
    max_redirects: int = MAX_REDIRECTS,
) -> FetchResult:
    """Fetch one page, raising :class:`FetchError` instead of failing silently.

    Every failure mode a single article can hit is turned into a distinct
    message, so a caller can fall back to the RSS summary and a human reading
    the log can see ``HTTP 403`` rather than "extraction failed".
    """
    headers = {"User-Agent": USER_AGENT, "Accept": accept}
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            max_redirects=max_redirects,
            headers=headers,
        ) as client:
            response = client.get(url)
    except httpx.TooManyRedirects as exc:
        raise FetchError(f"too many redirects (limit {max_redirects})") from exc
    except httpx.TimeoutException as exc:
        raise FetchError("request timed out") from exc
    except httpx.HTTPError as exc:
        raise FetchError(f"request failed: {exc.__class__.__name__}") from exc

    if response.status_code >= 400:
        raise FetchError(f"HTTP {response.status_code}", status=response.status_code)

    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    return FetchResult(
        url=str(response.url),
        status=response.status_code,
        content_type=content_type,
        text=response.text,
    )
