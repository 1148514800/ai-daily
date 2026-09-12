from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.collectors.github_trending import collect_trending
from app.config.github import MAX_PROJECTS, MIN_AI_SCORE
from app.models import GitHubProject
from app.pipelines.github_filter import is_ai_repo
from app.pipelines.github_normalize import project_from_trending
from app.services.github_client import GitHubClient, RepoMetadata
from app.services.llm.enrich import EnrichmentStats
from app.services.llm.github_enrich import enrich_github_projects

logger = logging.getLogger(__name__)


@dataclass
class GitHubRefreshStats:
    fetched: int = 0
    parsed: int = 0
    ai_candidates: int = 0
    metadata_success: int = 0
    selected: int = 0
    used_previous: bool = False
    error: str | None = None
    rate_limit_remaining: int | None = None
    rate_limit_limit: int | None = None
    llm_stats: EnrichmentStats = field(default_factory=EnrichmentStats)


class GitHubStore:
    def __init__(self) -> None:
        self.projects: list[GitHubProject] = []
        self.last_stats = GitHubRefreshStats()
        self.last_error: str | None = None

    def list_projects(self) -> list[GitHubProject]:
        return list(self.projects)

    def refresh(
        self,
        *,
        fetch_text=None,
        github_client: GitHubClient | None = None,
        enrich=None,
    ) -> GitHubRefreshStats:
        stats = GitHubRefreshStats()
        result = collect_trending(fetch_text=fetch_text)
        stats.fetched = result.fetched
        stats.parsed = len(result.parsed)
        stats.error = result.error

        if not result.success or not result.parsed:
            if self.projects:
                stats.used_previous = True
                stats.selected = len(self.projects)
                logger.warning("github trending failed; keeping previous snapshot error=%s", result.error)
                self.last_stats = stats
                self.last_error = result.error
                return stats
            self.projects = []
            self.last_stats = stats
            self.last_error = result.error
            return stats

        client = github_client or GitHubClient()
        candidates: list[GitHubProject] = []
        for raw in result.parsed:
            metadata: RepoMetadata | None = None
            if not client.rate_limited:
                owner, _, name = raw.repo.partition("/")
                metadata = client.get_repo(owner, name)
                if metadata is not None:
                    stats.metadata_success += 1
            if is_ai_repo(raw, metadata, threshold=MIN_AI_SCORE):
                candidates.append(project_from_trending(raw, metadata))

        stats.ai_candidates = len(candidates)
        selected = candidates[:MAX_PROJECTS]
        enrich_fn = enrich or enrich_github_projects
        try:
            projects, llm_stats = enrich_fn(selected)
        except Exception:
            logger.exception("github llm enrichment failed; using original descriptions")
            projects = selected
            llm_stats = EnrichmentStats(
                candidates=len(selected),
                fallback=len(selected),
                failed=len(selected),
            )
        stats.llm_stats = llm_stats
        stats.selected = len(projects)
        stats.rate_limit_remaining = client.rate_limit.remaining
        stats.rate_limit_limit = client.rate_limit.limit
        self.projects = projects
        self.last_stats = stats
        self.last_error = None
        logger.info(
            "github trending parsed=%s ai=%s selected=%s metadata=%s remaining=%s",
            stats.parsed,
            stats.ai_candidates,
            stats.selected,
            stats.metadata_success,
            stats.rate_limit_remaining,
        )
        return stats


github_store = GitHubStore()
