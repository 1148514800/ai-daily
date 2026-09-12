from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import httpx
from bs4 import BeautifulSoup

from app.collectors.raw import RawTrendingRepo
from app.config.github import TRENDING_URL

logger = logging.getLogger(__name__)
USER_AGENT = "ai-daily/0.1 (+https://github.com/1148514800/ai-daily)"
REPO_HREF_RE = re.compile(r"^/([^/]+)/([^/]+)/?$")
SKIP_OWNERS = {"topics", "trending", "explore", "settings", "orgs", "users", "login", "signup"}
COUNT_RE = re.compile(r"([0-9][0-9,]*)")
STARS_TODAY_RE = re.compile(r"([0-9][0-9,]*)\s+stars?\s+today", re.I)


@dataclass
class TrendingCollectResult:
    success: bool = True
    fetched: int = 0
    parsed: list[RawTrendingRepo] = field(default_factory=list)
    skipped: int = 0
    error: str | None = None


def fetch_trending_html(*, url: str = TRENDING_URL, timeout: float = 15.0, fetch_text=None) -> str:
    if fetch_text is not None:
        return fetch_text(url, timeout=timeout)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
    }
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.text


def _parse_int(text: str) -> int | None:
    match = COUNT_RE.search(text.replace("\n", " "))
    if not match:
        return None
    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _absolute_repo_url(href: str) -> str:
    if href.startswith("http://") or href.startswith("https://"):
        return href.split("?")[0].split("#")[0]
    return "https://github.com" + href


def _repo_from_href(href: str) -> tuple[str, str] | None:
    path = href.split("?")[0].split("#")[0]
    if path.startswith("https://github.com/"):
        path = path[len("https://github.com"):]
    if path.startswith("http://github.com/"):
        path = path[len("http://github.com"):]
    match = REPO_HREF_RE.match(path)
    if not match:
        return None
    owner, name = match.group(1), match.group(2)
    if owner in SKIP_OWNERS or name in {"stargazers", "forks", "issues"}:
        return None
    return owner, name


def parse_trending_html(html: str) -> TrendingCollectResult:
    result = TrendingCollectResult()
    soup = BeautifulSoup(html, "html.parser")
    articles = soup.select("article.Box-row")
    result.fetched = len(articles)
    if not articles:
        result.success = False
        result.error = "No trending repositories found"
        return result

    seen: set[str] = set()
    for article in articles:
        link = article.select_one("h2 a[href]")
        href = str(link.get("href") or "").strip() if link else ""
        parsed = _repo_from_href(href)
        if parsed is None:
            result.skipped += 1
            continue
        owner, name = parsed
        repo = f"{owner}/{name}"
        if repo.lower() in seen:
            result.skipped += 1
            continue
        seen.add(repo.lower())

        description_el = article.select_one("p")
        description = description_el.get_text(" ", strip=True) if description_el else ""
        language_el = article.select_one("[itemprop=programmingLanguage]")
        language = language_el.get_text(" ", strip=True) if language_el else ""

        stars = 0
        stargazers = article.select_one("a[href$='/stargazers']")
        if stargazers is not None:
            parsed_stars = _parse_int(stargazers.get_text(" ", strip=True))
            if parsed_stars is not None:
                stars = parsed_stars

        stars_today = None
        today_match = STARS_TODAY_RE.search(article.get_text(" ", strip=True))
        if today_match:
            try:
                stars_today = int(today_match.group(1).replace(",", ""))
            except ValueError:
                stars_today = None

        result.parsed.append(
            RawTrendingRepo(
                rank=len(result.parsed) + 1,
                repo=repo,
                name=name,
                description=description,
                language=language,
                url=_absolute_repo_url(href),
                stars=stars,
                stars_today=stars_today,
            )
        )
    return result


def collect_trending(*, url: str = TRENDING_URL, timeout: float = 15.0, fetch_text=None) -> TrendingCollectResult:
    try:
        if fetch_text is not None:
            html = fetch_text(url, timeout=timeout)
        else:
            html = fetch_trending_html(url=url, timeout=timeout)
    except Exception as exc:
        return TrendingCollectResult(success=False, error=str(exc) or exc.__class__.__name__)
    if not html or not str(html).strip():
        return TrendingCollectResult(success=False, error="Empty trending response")
    return parse_trending_html(str(html))
