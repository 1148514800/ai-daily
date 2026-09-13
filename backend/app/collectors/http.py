"""Shared HTTP fetching for the news collectors."""

from __future__ import annotations

import httpx

USER_AGENT = "ai-daily/0.1 (+https://github.com/1148514800/ai-daily)"
DEFAULT_TIMEOUT = 10.0
RSS_ACCEPT = "application/rss+xml, application/atom+xml, application/xml, text/xml"
HTML_ACCEPT = "text/html,application/xhtml+xml"


def fetch_text(url: str, *, timeout: float = DEFAULT_TIMEOUT, accept: str = HTML_ACCEPT) -> str:
    headers = {"User-Agent": USER_AGENT, "Accept": accept}
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.text
