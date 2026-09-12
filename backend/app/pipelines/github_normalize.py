from __future__ import annotations

import hashlib

from app.collectors.raw import RawTrendingRepo
from app.models import GitHubProject
from app.services.github_client import RepoMetadata


def stable_github_id(repo: str) -> str:
    digest = hashlib.sha256(repo.lower().encode("utf-8")).hexdigest()[:16]
    return f"gh-{digest}"


def project_from_trending(
    raw: RawTrendingRepo,
    metadata: RepoMetadata | None = None,
) -> GitHubProject:
    description = raw.description
    language = raw.language
    stars = raw.stars
    forks = None
    license_name = None
    topics: list[str] = []
    if metadata is not None:
        if metadata.description and not description:
            description = metadata.description
        if metadata.language and not language:
            language = metadata.language
        if metadata.stars is not None:
            stars = metadata.stars
        forks = metadata.forks
        license_name = metadata.license or None
        topics = list(metadata.topics)
    return GitHubProject(
        id=stable_github_id(raw.repo),
        repo=raw.repo,
        name=raw.name,
        description=description,
        language=language,
        stars=stars,
        stars_delta=raw.stars_today,
        summary_cn=description,
        why_it_matters="",
        url=raw.url,
        rank=raw.rank,
        forks=forks,
        license=license_name,
        topics=topics,
    )
