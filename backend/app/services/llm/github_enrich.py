from __future__ import annotations

import logging

from pydantic import ValidationError

from app.models import GitHubProject
from app.services.llm.cache import LLMCache
from app.services.llm.client import LLMClient, LLMError, parse_completion_json
from app.services.llm.enrich import EnrichmentStats
from app.services.llm.github_prompts import (
    GITHUB_PROMPT_VERSION,
    GITHUB_SYSTEM_PROMPT,
    build_github_user_prompt,
)
from app.services.llm.schemas import GitHubEnrichment
from app.services.llm.settings import LLMSettings, load_llm_settings

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 2


def _fallback(project: GitHubProject) -> GitHubProject:
    return project.model_copy(update={"summary_cn": project.description, "why_it_matters": ""})


def _cache_key(cache: LLMCache, project: GitHubProject, settings: LLMSettings) -> str:
    return cache.hash_parts(
        project.repo,
        project.description,
        ",".join(project.topics),
        settings.model,
        GITHUB_PROMPT_VERSION,
    )


def enrich_github_project(
    project: GitHubProject,
    *,
    settings: LLMSettings,
    cache: LLMCache,
    client: LLMClient,
    stats: EnrichmentStats,
) -> GitHubProject:
    key = _cache_key(cache, project, settings)
    cached = cache.get_model(key, GitHubEnrichment)
    if cached is not None:
        stats.cache_hits += 1
        return project.model_copy(
            update={"summary_cn": cached.summary_cn.strip(), "why_it_matters": cached.why_it_matters.strip()}
        )

    if not settings.available:
        stats.fallback += 1
        return _fallback(project)

    messages = [
        {"role": "system", "content": GITHUB_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": build_github_user_prompt(
                repo=project.repo,
                description=project.description,
                language=project.language,
                topics=", ".join(project.topics),
                stars=project.stars,
                stars_today=project.stars_delta,
                rank=project.rank,
            ),
        },
    ]
    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        stats.llm_calls += 1
        try:
            completion = client.complete(messages)
            stats.add_usage(completion)
            payload = parse_completion_json(completion.text)
            enrichment = GitHubEnrichment.model_validate(payload)
            cache.set_model(key, enrichment)
            stats.success += 1
            return project.model_copy(
                update={
                    "summary_cn": enrichment.summary_cn.strip(),
                    "why_it_matters": enrichment.why_it_matters.strip(),
                }
            )
        except (LLMError, ValidationError, ValueError, TypeError) as exc:
            last_error = exc
            logger.warning(
                "github llm enrich failed attempt=%s/%s repo=%s error=%s",
                attempt + 1,
                MAX_ATTEMPTS,
                project.repo,
                exc,
            )
    stats.failed += 1
    stats.fallback += 1
    logger.warning("github llm fallback repo=%s error=%s", project.repo, last_error)
    return _fallback(project)


def enrich_github_projects(
    projects: list[GitHubProject],
    *,
    settings: LLMSettings | None = None,
    cache: LLMCache | None = None,
    client: LLMClient | None = None,
) -> tuple[list[GitHubProject], EnrichmentStats]:
    resolved = settings or load_llm_settings()
    stats = EnrichmentStats(candidates=len(projects), enabled=resolved.enabled, available=resolved.available)
    resolved_cache = cache or LLMCache(resolved.cache_dir)
    resolved_client = client or LLMClient(resolved)
    items: list[GitHubProject] = []
    for project in projects:
        try:
            items.append(
                enrich_github_project(
                    project,
                    settings=resolved,
                    cache=resolved_cache,
                    client=resolved_client,
                    stats=stats,
                )
            )
        except Exception:
            logger.exception("github llm enrich crashed repo=%s", project.repo)
            stats.failed += 1
            stats.fallback += 1
            items.append(_fallback(project))
    return items, stats
