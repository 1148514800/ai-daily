from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.collectors.raw import RawTrendingRepo
from app.config.github import (
    CORE_AI_KEYWORDS,
    DESCRIPTION_STRONG_SCORE,
    EXTRA_STRONG_SCORE,
    MAX_EXTRA_STRONG_SCORE,
    MAX_WEAK_SCORE,
    MIN_AI_SCORE,
    NAME_STRONG_SCORE,
    NEGATIVE_HINTS,
    STRICT_MIN_AI_SCORE,
    TOOLING_AI_KEYWORDS,
    TOPIC_STRONG_SCORE,
    WEAK_AI_KEYWORDS,
    WEAK_HIT_SCORE,
    WEAK_MIN_COUNT,
)
from app.services.github_client import RepoMetadata

FIELD_TOPICS = "topics"
FIELD_DESCRIPTION = "description"
FIELD_NAME = "name"
FIELD_ORDER = (FIELD_TOPICS, FIELD_DESCRIPTION, FIELD_NAME)

# Fields that speak for the project itself. GitHub topics are self-declared
# labels that anyone can stuff, so topics add score and corroborate but can
# never accept a repository on their own.
CONTENT_FIELDS = (FIELD_DESCRIPTION, FIELD_NAME)

# Repo names containing these are explicit AI evidence on their own.
EXPLICIT_NAME_KEYWORDS: tuple[str, ...] = (
    "llm",
    "large language model",
    "stable diffusion",
    "transformer",
    "rag",
)

MODE_NORMAL = "normal"
MODE_STRICT = "strict"

ROUTE_CORE = "core"
ROUTE_EXPLICIT_NAME = "explicit-name"
ROUTE_TOOLING = "tooling"
ROUTE_WEAK = "weak-keywords"
ROUTE_NONE = "none"


def _normalize(text: str) -> str:
    return re.sub(r"[-_/]+", " ", text.lower())


def _keyword_hit(text: str, keyword: str) -> bool:
    haystack = _normalize(text)
    needle = _normalize(keyword)
    if not haystack or not needle:
        return False
    if " " in needle:
        return needle in haystack
    return re.search(rf"(?<![a-z0-9]){re.escape(needle)}s?(?![a-z0-9])", haystack) is not None


def _matches(text: str, keywords: tuple[str, ...]) -> list[str]:
    return [keyword for keyword in keywords if _keyword_hit(text, keyword)]


def _unique_in_field_order(by_field: dict[str, list[str]]) -> list[str]:
    seen: list[str] = []
    for name in FIELD_ORDER:
        for keyword in by_field.get(name, []):
            if keyword not in seen:
                seen.append(keyword)
    return seen


@dataclass
class AIRelevance:
    """Deterministic AI relevance evidence for a single trending repository."""

    score: int = 0
    accepted: bool = False
    mode: str = MODE_NORMAL
    route: str = ROUTE_NONE
    reason: str = ""
    strong_by_field: dict[str, list[str]] = field(default_factory=dict)
    weak_by_field: dict[str, list[str]] = field(default_factory=dict)
    negative_keywords: list[str] = field(default_factory=list)
    extra_strong: list[str] = field(default_factory=list)

    @property
    def strong_keywords(self) -> list[str]:
        return _unique_in_field_order(self.strong_by_field)

    @property
    def weak_keywords(self) -> list[str]:
        return _unique_in_field_order(self.weak_by_field)

    @property
    def weak_fields(self) -> list[str]:
        return [name for name in FIELD_ORDER if self.weak_by_field.get(name)]

    @property
    def matched_fields(self) -> list[str]:
        return [
            name
            for name in FIELD_ORDER
            if self.strong_by_field.get(name) or self.weak_by_field.get(name)
        ]

    def _keywords_in(self, fields: tuple[str, ...], keywords: tuple[str, ...]) -> list[str]:
        return [
            keyword
            for name in fields
            for keyword in self.strong_by_field.get(name, [])
            if keyword in keywords
        ]

    def any_core(self) -> list[str]:
        """Core AI keywords anywhere, including self-declared topics."""
        return self._keywords_in(FIELD_ORDER, CORE_AI_KEYWORDS)

    def content_core(self) -> list[str]:
        """Core AI keywords from the description or repo name."""
        return self._keywords_in(CONTENT_FIELDS, CORE_AI_KEYWORDS)

    def content_tooling(self) -> list[str]:
        return self._keywords_in(CONTENT_FIELDS, TOOLING_AI_KEYWORDS)

    def has_explicit_name(self) -> bool:
        names = self.strong_by_field.get(FIELD_NAME, [])
        return any(keyword in EXPLICIT_NAME_KEYWORDS for keyword in names)

    def weak_corroborated(self) -> bool:
        """Two weak keywords in different fields, plus core AI evidence.

        "agent" and "model" in one sentence are not independent, so the weak
        keywords must land in different fields. A core AI keyword must also be
        present, so tooling-only projects cannot pass on marketing copy.
        """
        if len(self.weak_keywords) < WEAK_MIN_COUNT or len(self.weak_fields) < 2:
            return False
        return bool(self.any_core())


def _score_strong(result: AIRelevance) -> None:
    if result.strong_by_field.get(FIELD_TOPICS):
        result.score += TOPIC_STRONG_SCORE
    if result.strong_by_field.get(FIELD_DESCRIPTION):
        result.score += DESCRIPTION_STRONG_SCORE
    if result.strong_by_field.get(FIELD_NAME):
        result.score += NAME_STRONG_SCORE

    budget = MAX_EXTRA_STRONG_SCORE
    for name in FIELD_ORDER:
        for keyword in result.strong_by_field.get(name, [])[1:]:
            if budget <= 0:
                return
            result.extra_strong.append(f"{name}:{keyword}")
            result.score += EXTRA_STRONG_SCORE
            budget -= 1


def _score_weak(result: AIRelevance) -> None:
    if not result.weak_keywords:
        return
    result.score += min(len(result.weak_keywords) * WEAK_HIT_SCORE, MAX_WEAK_SCORE)


def _decide(result: AIRelevance, *, strict: bool) -> None:
    """Apply the acceptance rules in priority order.

    Core AI evidence in the project's own description or name always wins. When
    core evidence only appears in self-declared topics, it needs supporting
    score. Tooling keywords (for example MCP) never accept on their own: they
    must be corroborated by core AI evidence, because many ordinary developer
    tools now advertise "MCP tools" or "AI agents" without being AI projects.
    """
    content_core = result.content_core()
    content_tooling = result.content_tooling()
    core_anywhere = result.any_core()

    if strict:
        # Strict fallback: metadata is unavailable, so trust only the Trending
        # page text and apply the higher strict threshold. Only genuinely
        # unambiguous names bypass it.
        if content_core and result.score >= STRICT_MIN_AI_SCORE:
            result.accepted, result.route = True, ROUTE_CORE
            result.reason = "core AI keyword above strict threshold"
        elif result.has_explicit_name():
            result.accepted, result.route = True, ROUTE_EXPLICIT_NAME
            result.reason = "explicit AI keyword in repo name"
        else:
            result.accepted, result.route = False, ROUTE_NONE
            if content_core:
                result.reason = f"score {result.score} below strict threshold {STRICT_MIN_AI_SCORE}"
            elif result.strong_keywords:
                result.reason = "strict fallback rejects topics-only or tooling-only evidence"
            elif result.weak_keywords:
                result.reason = "weak AI keywords alone are not enough"
            else:
                result.reason = "no strong AI evidence"
    elif content_core:
        result.accepted, result.route = True, ROUTE_CORE
        result.reason = "core AI keyword in description/name"
    elif result.has_explicit_name():
        result.accepted, result.route = True, ROUTE_EXPLICIT_NAME
        result.reason = "explicit AI keyword in repo name"
    elif core_anywhere and result.score >= MIN_AI_SCORE:
        result.accepted, result.route = True, ROUTE_CORE
        result.reason = "core AI keyword in topics with supporting score"
    elif content_tooling and core_anywhere:
        result.accepted, result.route = True, ROUTE_TOOLING
        result.reason = "AI tooling keyword corroborated by core AI evidence"
    elif result.weak_corroborated():
        result.accepted, result.route = True, ROUTE_WEAK
        result.reason = "independent weak AI keywords with core AI evidence"
    else:
        result.accepted, result.route = False, ROUTE_NONE
        if result.strong_keywords:
            result.reason = "tooling/topics-only evidence without core AI keyword"
        elif result.weak_keywords:
            result.reason = "weak AI keywords alone are not enough"
        else:
            result.reason = "no strong AI evidence"

    # Negative hints veto everything except core AI evidence in the project's
    # own description or name, per the phase spec.
    if result.negative_keywords and not content_core:
        result.accepted, result.route = False, ROUTE_NONE
        result.reason = "negative hint without core AI evidence: " + ", ".join(result.negative_keywords)


def evaluate_ai_relevance(
    raw: RawTrendingRepo,
    metadata: RepoMetadata | None = None,
    *,
    strict: bool | None = None,
) -> AIRelevance:
    """Score a trending repo for AI relevance using deterministic evidence.

    Strong keywords score by field (topics +4, description +3, name +2) and weak
    keywords add +1 each up to a cap. Acceptance always needs core AI evidence
    somewhere, so a single weak keyword such as "agent" or "model" never passes,
    self-declared topics never pass alone, and tooling keywords such as MCP must
    be corroborated. This is what removes the earlier false positives, where
    CRM or desktop utilities were accepted purely from marketing copy.

    Strict mode is used when REST metadata is unavailable (for example anonymous
    rate limits). It requires core AI evidence in the description or name above
    STRICT_MIN_AI_SCORE, or an unambiguous name such as "llm".
    """
    use_strict = strict if strict is not None else metadata is None
    result = AIRelevance(mode=MODE_STRICT if use_strict else MODE_NORMAL)

    description = raw.description
    topics = ""
    if metadata is not None:
        if metadata.description:
            description = f"{description} {metadata.description}".strip()
        topics = " ".join(metadata.topics)
    name_text = f"{raw.repo} {raw.name}"

    for name, text in (
        (FIELD_TOPICS, topics),
        (FIELD_DESCRIPTION, description),
        (FIELD_NAME, name_text),
    ):
        if not text:
            continue
        core = _matches(text, CORE_AI_KEYWORDS)
        tooling = _matches(text, TOOLING_AI_KEYWORDS)
        strong = core + [keyword for keyword in tooling if keyword not in core]
        weak = _matches(text, WEAK_AI_KEYWORDS)
        if strong:
            result.strong_by_field[name] = strong
        if weak:
            result.weak_by_field[name] = weak

    combined = f"{topics} {description} {name_text}"
    result.negative_keywords = _matches(combined, NEGATIVE_HINTS)

    _score_strong(result)
    _score_weak(result)
    _decide(result, strict=use_strict)
    return result


def ai_relevance_score(raw: RawTrendingRepo, metadata: RepoMetadata | None = None) -> int:
    return evaluate_ai_relevance(raw, metadata).score


def is_ai_repo(raw: RawTrendingRepo, metadata: RepoMetadata | None = None) -> bool:
    return evaluate_ai_relevance(raw, metadata).accepted
