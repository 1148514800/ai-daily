from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.collectors.github_trending import collect_trending
from app.config.github import MAX_PROJECTS
from app.models import GitHubProject
from app.pipelines.github_filter import AIRelevance, evaluate_ai_relevance
from app.pipelines.github_normalize import project_from_trending
from app.services.github_client import GitHubClient, RepoMetadata
from app.services.llm.enrich import EnrichmentStats
from app.services.llm.github_enrich import enrich_github_projects

logger = logging.getLogger(__name__)


@dataclass
class RepoDecision:
    """One accept/reject decision, kept for logging and debug output."""

    rank: int
    repo: str
    accepted: bool
    score: int
    route: str
    reason: str
    mode: str
    strong: list[str]
    weak: list[str]
    matched_fields: list[str]
    negative: list[str]
    metadata_available: bool

    @classmethod
    def from_relevance(
        cls,
        rank: int,
        repo: str,
        relevance: AIRelevance,
        *,
        metadata_available: bool,
    ) -> "RepoDecision":
        return cls(
            rank=rank,
            repo=repo,
            accepted=relevance.accepted,
            score=relevance.score,
            route=relevance.route,
            reason=relevance.reason,
            mode=relevance.mode,
            strong=relevance.strong_keywords,
            weak=relevance.weak_keywords,
            matched_fields=relevance.matched_fields,
            negative=relevance.negative_keywords,
            metadata_available=metadata_available,
        )


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
    decisions: list[RepoDecision] = field(default_factory=list)


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
        decisions: list[RepoDecision] = []
        for raw in result.parsed:
            metadata: RepoMetadata | None = None
            if not client.rate_limited:
                owner, _, name = raw.repo.partition("/")
                metadata = client.get_repo(owner, name)
                if metadata is not None:
                    stats.metadata_success += 1
            # Missing metadata automatically switches the filter to strict mode,
            # so anonymous rate limits cannot inflate the candidate list.
            relevance = evaluate_ai_relevance(raw, metadata)
            decisions.append(
                RepoDecision.from_relevance(
                    raw.rank,
                    raw.repo,
                    relevance,
                    metadata_available=metadata is not None,
                )
            )
            if relevance.accepted:
                candidates.append(project_from_trending(raw, metadata))

        stats.decisions = decisions
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
