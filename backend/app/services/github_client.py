from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx

from app.config.env import load_dotenv
from app.config.github import GITHUB_API_BASE

logger = logging.getLogger(__name__)
USER_AGENT = "ai-daily/0.1 (+https://github.com/1148514800/ai-daily)"


class GitHubRateLimitError(Exception):
    pass


@dataclass(frozen=True)
class RepoMetadata:
    stars: int | None = None
    forks: int | None = None
    language: str = ""
    license: str = ""
    topics: tuple[str, ...] = ()
    description: str = ""
    updated_at: str = ""


@dataclass
class RateLimit:
    limit: int | None = None
    remaining: int | None = None
    reset: int | None = None


def _int_header(headers: httpx.Headers, name: str) -> int | None:
    value = headers.get(name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def is_rate_limit_response(response: httpx.Response) -> bool:
    if response.status_code not in {403, 429}:
        return False
    remaining = response.headers.get("x-ratelimit-remaining")
    if remaining == "0":
        return True
    text = response.text.lower()
    return "rate limit" in text or "secondary rate" in text


class GitHubClient:
    def __init__(self, *, token: str | None = None, timeout: float = 10.0, transport=None) -> None:
        load_dotenv()
        self.token = (token if token is not None else os.getenv("GITHUB_TOKEN", "")).strip()
        self.timeout = timeout
        self.transport = transport
        self.rate_limit = RateLimit()
        self.rate_limited = False

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _record_rate_limit(self, response: httpx.Response) -> None:
        self.rate_limit = RateLimit(
            limit=_int_header(response.headers, "x-ratelimit-limit"),
            remaining=_int_header(response.headers, "x-ratelimit-remaining"),
            reset=_int_header(response.headers, "x-ratelimit-reset"),
        )
        logger.info(
            "github ratelimit limit=%s remaining=%s reset=%s",
            self.rate_limit.limit,
            self.rate_limit.remaining,
            self.rate_limit.reset,
        )

    def get_repo(self, owner: str, name: str) -> RepoMetadata | None:
        if self.rate_limited:
            return None
        url = f"{GITHUB_API_BASE}/repos/{owner}/{name}"
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                with httpx.Client(timeout=self.timeout, transport=self.transport, follow_redirects=True) as client:
                    response = client.get(url, headers=self._headers())
                self._record_rate_limit(response)
                if is_rate_limit_response(response):
                    if attempt == 0:
                        continue
                    self.rate_limited = True
                    logger.warning("github rate limit reached; using trending fallback")
                    return None
                if response.status_code >= 400:
                    last_error = httpx.HTTPStatusError(
                        f"{response.status_code}",
                        request=response.request,
                        response=response,
                    )
                    continue
                payload = response.json()
                license_info = payload.get("license") or {}
                license_name = ""
                if isinstance(license_info, dict):
                    license_name = str(license_info.get("spdx_id") or license_info.get("name") or "")
                topics = payload.get("topics") or []
                if not isinstance(topics, list):
                    topics = []
                return RepoMetadata(
                    stars=payload.get("stargazers_count") if isinstance(payload.get("stargazers_count"), int) else None,
                    forks=payload.get("forks_count") if isinstance(payload.get("forks_count"), int) else None,
                    language=str(payload.get("language") or ""),
                    license=license_name,
                    topics=tuple(str(item) for item in topics if item),
                    description=str(payload.get("description") or ""),
                    updated_at=str(payload.get("updated_at") or ""),
                )
            except httpx.TimeoutException as exc:
                last_error = exc
                logger.warning("github repo timeout owner=%s name=%s", owner, name)
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning("github repo http error owner=%s name=%s", owner, name)
        if last_error:
            logger.warning("github repo fallback owner=%s name=%s error=%s", owner, name, last_error)
        return None
