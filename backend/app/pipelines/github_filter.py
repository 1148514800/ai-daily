from __future__ import annotations

import re

from app.collectors.raw import RawTrendingRepo
from app.config.github import (
    AI_KEYWORDS,
    DESCRIPTION_HIT_SCORE,
    MIN_AI_SCORE,
    NAME_HIT_SCORE,
    TOPIC_HIT_SCORE,
)
from app.services.github_client import RepoMetadata


def _normalize(text: str) -> str:
    return re.sub(r"[-_/]+", " ", text.lower())


def _keyword_hit(text: str, keyword: str) -> bool:
    haystack = _normalize(text)
    needle = _normalize(keyword)
    if not haystack or not needle:
        return False
    if " " in needle:
        return needle in haystack
    return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack) is not None


def _any_keyword(text: str) -> bool:
    return any(_keyword_hit(text, keyword) for keyword in AI_KEYWORDS)


def ai_relevance_score(raw: RawTrendingRepo, metadata: RepoMetadata | None = None) -> int:
    score = 0
    name_text = f"{raw.repo} {raw.name}"
    description = raw.description
    topics = ""
    if metadata is not None:
        if metadata.description:
            description = f"{description} {metadata.description}".strip()
        topics = " ".join(metadata.topics)
    if _any_keyword(topics):
        score += TOPIC_HIT_SCORE
    if _any_keyword(description):
        score += DESCRIPTION_HIT_SCORE
    if _any_keyword(name_text):
        score += NAME_HIT_SCORE
    return score


def is_ai_repo(raw: RawTrendingRepo, metadata: RepoMetadata | None = None, *, threshold: int = MIN_AI_SCORE) -> bool:
    return ai_relevance_score(raw, metadata) >= threshold
