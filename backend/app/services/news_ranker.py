"""Deterministic ranking and diversity reranking for one digest.

A refresh can produce a few dozen candidates. The digest is read top-down, so
the order is what decides whether the first screen is worth reading. This module
turns a collected set into that order.

Three properties are non-negotiable:

* **Deterministic.** The same articles always produce the same order. No
  randomness, no clock read, no dependence on dict or set iteration order: every
  comparison ends in a stable tie breaker (``published_at``, then ``news_id``).
* **Explainable.** Each entry carries the score components that produced it, so
  "why is this first?" is answered by numbers rather than by a model.
* **Non-destructive.** Ranking never drops an article. Diversity is a soft
  penalty, so three genuinely big OpenAI stories can still all sit in the top
  ten; a quieter story is only moved up when the ones above it are redundant.

The LLM contributes ``importance_score`` and nothing else. Asking a model to
order thirty articles would be unstable, expensive, and impossible to test, so
the final order is always computed here.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone

from app.models import NewsItem
from app.config.ranking import DEFAULT_TOP_STORY_LIMIT
from app.services.article_extractor import (
    METHOD_RSS_FULL,
    METHOD_RSS_SUMMARY,
    METHOD_WEB,
)
from app.services.news_topics import TOPIC_OTHER, label_article

logger = logging.getLogger(__name__)

RANK_DEBUG_ENV = "AI_DAILY_DEBUG_RANKING"

# Source class weights, matching how the rest of the pipeline already thinks
# about provenance: a first-party announcement outranks a community write-up,
# which outranks second-hand reporting. The gap is deliberately small, because a
# big media story has to be able to overtake a minor official one.
SOURCE_TYPE_RANKS = {"official": 1.0, "blog": 0.6, "media": 0.35}
UNKNOWN_SOURCE_TYPE_RANK = 0.3

# How the body was obtained. Having real text is a weak signal: a long article
# is not more important than a short one, it is merely cheaper to summarise and
# read in the detail view.
CONTENT_METHOD_RANKS = {
    METHOD_WEB: 1.0,
    METHOD_RSS_FULL: 0.9,
    METHOD_RSS_SUMMARY: 0.3,
    "": 0.2,
}

# Body length saturates: past this many characters an article is simply "long",
# so a 20k-character post does not outrank a 6k one on size alone.
CONTENT_LENGTH_SATURATION = 4000

# A recency bonus applies linearly across the digest window, so the newest
# article earns the full weight and the oldest earns none. It is a tie-breaker
# between comparable stories, never a reason to prefer a trivial fresh one.
RECENCY_FLOOR = 0.0


@dataclass(frozen=True)
class RankingSettings:
    """Every ranking number, in one place.

    ``top_story_limit`` is also the API's ``is_top_story`` boundary, so the
    client and the ranker never disagree about what "top" means. Penalties are
    sized to reorder comparable stories only: they are subtracted from a score
    in the 0..100 range, so a penalty can never lift a weak story above a strong
    one by itself.
    """

    top_story_limit: int = DEFAULT_TOP_STORY_LIMIT
    # Component weights, as a share of the final 0..100 score.
    importance_weight: float = 0.60
    source_weight: float = 0.14
    recency_weight: float = 0.10
    content_weight: float = 0.06
    # A small bonus for an event several independent outlets reported. Capped at
    # one merge so a story does not climb on repetition alone.
    cluster_weight: float = 0.10
    cluster_bonus_per_extra_source: float = 0.5
    cluster_bonus_cap: float = 2.0
    # Soft diversity penalties, applied while the order is assembled. Sizes are
    # in the same units as the 0..100 score, so they can separate two comparable
    # stories but not two clearly different ones: the cap is worth roughly the
    # importance band that separates a major story from a routine one, which
    # keeps a genuinely bigger story in front of a merely different one.
    company_repeat_penalty: float = 3.0
    topic_repeat_penalty: float = 2.0
    source_repeat_penalty: float = 1.0
    # Ceiling on the total penalty one story can carry. Without it a long run of
    # one company would let the penalty grow without bound; with it the worst a
    # story can lose is bounded, so a genuinely important one still leads.
    max_diversity_penalty: float = 8.0
    # Importance is unknown for un-enriched articles; this is the neutral value
    # used instead, low enough that such a story cannot lead a digest on its own.
    default_importance: float = 35.0


DEFAULT_SETTINGS = RankingSettings()


def ranking_debug_enabled() -> bool:
    """Per-article ranking logging, opt-in so default logs stay short."""
    return os.getenv(RANK_DEBUG_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _published_at(item: NewsItem) -> datetime | None:
    if not item.published_at:
        return None
    try:
        moment = datetime.fromisoformat(item.published_at)
    except ValueError:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


@dataclass(frozen=True)
class RankComponents:
    """The contribution of each signal to one story's score."""

    importance: float
    source: float
    recency: float
    content: float
    cluster: float
    # Negative: what diversity took away while the top stories were assembled.
    diversity: float = 0.0

    def describe(self) -> str:
        return (
            f"importance={self.importance:.1f} source={self.source:.1f} "
            f"recency={self.recency:.1f} content={self.content:.1f} "
            f"cluster={self.cluster:.1f} diversity={self.diversity:.1f}"
        )


@dataclass(frozen=True)
class RankedNews:
    """One story with its place in the digest and the reason for it."""

    news_id: str
    rank: int
    rank_score: float
    rank_reason: str
    rank_components: RankComponents
    is_top_story: bool
    topic: str
    company: str

    def describe(self) -> str:
        return (
            f"#{self.rank} score={self.rank_score:.1f} {self.rank_components.describe()} "
            f"topic={self.topic} company={self.company or '-'} reason={self.rank_reason}"
        )


@dataclass
class RankingStats:
    candidates: int = 0
    top_stories: int = 0
    topics: int = 0
    companies: int = 0
    ranked: list[RankedNews] = field(default_factory=list)


def _content_component(item: NewsItem) -> float:
    """How complete the stored body is, as a 0..1 signal."""
    method = CONTENT_METHOD_RANKS.get(item.content_extraction_method, 0.2)
    length = len(item.content_original or "")
    length_signal = min(length / CONTENT_LENGTH_SATURATION, 1.0)
    # Method dominates length: a real body from a page beats a slightly longer
    # feed teaser, and length only separates two articles obtained the same way.
    return round(method * (1.0 + length_signal) / 2.0, 4)


def _importance_component(item: NewsItem, settings: RankingSettings) -> float:
    """``importance_score`` normalised to 0..1, with a neutral fallback."""
    if item.importance_score is None:
        raw = settings.default_importance
    else:
        raw = float(item.importance_score)
    return max(0.0, min(raw, 100.0)) / 100.0


def _source_component(item: NewsItem) -> float:
    return SOURCE_TYPE_RANKS.get(item.source_type, UNKNOWN_SOURCE_TYPE_RANK)


def _recency_component(
    published: datetime | None,
    *,
    window_start: datetime | None,
    window_end: datetime | None,
) -> float:
    """0..1 position of ``published`` inside the digest window.

    Without a window the signal is dropped rather than guessed, so a caller that
    ranks articles outside a digest (a rebuild, a test) still gets a stable
    order from the remaining components.
    """
    if published is None or window_start is None or window_end is None:
        return RECENCY_FLOOR
    span = (window_end - window_start).total_seconds()
    if span <= 0:
        return RECENCY_FLOOR
    position = (published - window_start).total_seconds() / span
    return max(0.0, min(position, 1.0))


def _reason(item: NewsItem, topic: str, company: str, components: RankComponents) -> str:
    """A short human explanation, e.g. ``high importance + official source``."""
    parts: list[str] = []
    score = item.importance_score
    if score is not None and score >= 80:
        parts.append("high importance")
    elif score is not None and score >= 50:
        parts.append("notable importance")
    rank = SOURCE_TYPE_RANKS.get(item.source_type, UNKNOWN_SOURCE_TYPE_RANK)
    if rank >= 1.0:
        parts.append("official source")
    elif item.source_type == "blog":
        parts.append("community source")
    else:
        parts.append("media source")
    if components.content >= 0.6:
        parts.append("full text")
    if components.cluster > 0:
        parts.append("multi-source event")
    if topic:
        parts.append(topic.replace("_", " "))
    if company:
        parts.append(company)
    return " + ".join(parts)


def _base_components(
    item: NewsItem,
    *,
    window_start: datetime | None,
    window_end: datetime | None,
    cluster_size: int,
    settings: RankingSettings,
) -> RankComponents:
    extra_sources = max(0, cluster_size - 1)
    cluster = min(
        extra_sources * settings.cluster_bonus_per_extra_source,
        settings.cluster_bonus_cap,
    )
    return RankComponents(
        importance=_importance_component(item, settings),
        source=_source_component(item),
        recency=_recency_component(
            _published_at(item), window_start=window_start, window_end=window_end
        ),
        content=_content_component(item),
        cluster=cluster,
    )


def _base_score(components: RankComponents, settings: RankingSettings) -> float:
    """The 0..100 score before diversity. Weights sum to <= 1 plus the bonus."""
    weighted = (
        components.importance * settings.importance_weight
        + components.source * settings.source_weight
        + components.recency * settings.recency_weight
        + components.content * settings.content_weight
        + components.cluster * settings.cluster_weight
    )
    return round(weighted * 100.0, 4)


def _diversity_penalty(
    chosen: list["_Candidate"],
    candidate: "_Candidate",
    settings: RankingSettings,
) -> float:
    """What picking ``candidate`` next would cost, given what is already chosen.

    Each already-chosen story that shares the candidate's company, topic or
    source adds a fixed amount, capped so a long run of one company cannot bury
    a story outright. The result is a soft nudge: a strong story still leads, a
    comparable near-duplicate of the leader yields.
    """
    penalty = 0.0
    companies = 0
    topics = 0
    sources = 0
    for previous in chosen:
        if candidate.company and candidate.company == previous.company:
            companies += 1
        # ``other`` is "we could not tell", not a topic two stories share, so it
        # never counts as repetition: penalising it would push apart unrelated
        # stories that merely both failed to classify.
        if candidate.topic != TOPIC_OTHER and candidate.topic == previous.topic:
            topics += 1
        if candidate.item.source and candidate.item.source == previous.item.source:
            sources += 1
    penalty = (
        companies * settings.company_repeat_penalty
        + topics * settings.topic_repeat_penalty
        + sources * settings.source_repeat_penalty
    )
    return round(min(penalty, settings.max_diversity_penalty), 4)


@dataclass
class _Candidate:
    item: NewsItem
    topic: str
    company: str
    components: RankComponents
    base_score: float

    @property
    def sort_key(self) -> tuple:
        """Stable tie breaker: final score, then newest, then id.

        The final score includes the diversity penalty, so the greedy pass
        compares candidates exactly the way the finished list is ordered. Using
        the pre-penalty score here would make the penalty invisible to the very
        comparison it exists to influence.

        ``news_id`` is unique, so two candidates can never compare equal and the
        order never depends on how the input list happened to be built.
        """
        published = _published_at(self.item)
        stamp = published.timestamp() if published is not None else float("-inf")
        final = self.base_score + self.components.diversity
        return (-final, -stamp, self.item.id)


def rank_news(
    items: list[NewsItem],
    *,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    cluster_sizes: dict[str, int] | None = None,
    top_story_limit: int | None = None,
    settings: RankingSettings = DEFAULT_SETTINGS,
) -> tuple[list[RankedNews], RankingStats]:
    """Order ``items`` best-first and mark the top stories.

    Every item survives: the returned list has one entry per input item, ranked
    from 1. ``cluster_sizes`` maps a news id to how many sources reported its
    event, which lets a corroborated story earn a small bonus without this
    module needing to know anything about clustering.
    """
    effective = (
        settings
        if top_story_limit is None
        else replace(settings, top_story_limit=top_story_limit)
    )

    stats = RankingStats(candidates=len(items))
    if not items:
        return [], stats

    sizes = cluster_sizes or {}
    candidates = [
        _candidate(item, sizes.get(item.id, 1), window_start, window_end, effective)
        for item in items
    ]

    # Greedy over the whole list, not just the head. Stopping the diversity pass
    # at the top-story boundary would leave two incompatible orderings in one
    # digest: a penalised top ten followed by an unpenalised tail whose scores
    # could exceed the entry above it. Running it end to end keeps rank_score
    # non-increasing down the digest, which is what makes the number meaningful.
    ordered = _greedy_order(candidates, effective)

    ranked: list[RankedNews] = []
    for index, candidate in enumerate(ordered, start=1):
        ranked.append(
            RankedNews(
                news_id=candidate.item.id,
                rank=index,
                rank_score=round(candidate.base_score + candidate.components.diversity, 4),
                rank_reason=_reason(
                    candidate.item, candidate.topic, candidate.company, candidate.components
                ),
                rank_components=candidate.components,
                is_top_story=index <= effective.top_story_limit,
                topic=candidate.topic,
                company=candidate.company,
            )
        )

    stats.top_stories = min(effective.top_story_limit, len(ranked))
    stats.topics = len({entry.topic for entry in ranked})
    stats.companies = len({entry.company for entry in ranked if entry.company})
    stats.ranked = ranked
    return ranked, stats


def _greedy_order(
    candidates: list[_Candidate],
    settings: RankingSettings,
) -> list[_Candidate]:
    """Order the whole digest greedily, penalising repetition as it goes.

    Each position takes the best remaining story after subtracting what its
    company, topic and source would repeat from the stories already placed. The
    penalty is capped, so a much stronger story still wins its position; the
    effect is to interleave comparable stories rather than to enforce a quota.
    Because every step takes the current maximum and a story's capped penalty
    can only grow as more stories are placed, the stored score never rises
    further down the list.
    """
    remaining = list(candidates)
    chosen: list[_Candidate] = []
    while remaining:
        best_index = 0
        best_key: tuple | None = None
        best_candidate: _Candidate | None = None
        for index, candidate in enumerate(remaining):
            penalty = _diversity_penalty(chosen, candidate, settings)
            adjusted = _with_diversity(candidate, penalty)
            key = adjusted.sort_key
            if best_key is None or key < best_key:
                best_key = key
                best_index = index
                best_candidate = adjusted
        remaining.pop(best_index)
        # The penalty is kept on the chosen entry, so the final score the caller
        # stores is the one the ordering was actually computed from.
        chosen.append(best_candidate or candidates[0])
    return chosen


def _with_diversity(candidate: _Candidate, penalty: float) -> _Candidate:
    """A copy carrying the diversity penalty, used only for the next pick."""
    components = RankComponents(
        importance=candidate.components.importance,
        source=candidate.components.source,
        recency=candidate.components.recency,
        content=candidate.components.content,
        cluster=candidate.components.cluster,
        diversity=-penalty,
    )
    return _Candidate(
        item=candidate.item,
        topic=candidate.topic,
        company=candidate.company,
        components=components,
        base_score=candidate.base_score,
    )


def _candidate(
    item: NewsItem,
    cluster_size: int,
    window_start: datetime | None,
    window_end: datetime | None,
    settings: RankingSettings,
) -> _Candidate:
    """Label one article and score it.

    The labels come from the shared helpers in ``news_topics``, so the API
    reports exactly the topics this ordering was computed from instead of a
    second copy of the rules.
    """
    topic, company = label_article(item)
    components = _base_components(
        item,
        window_start=window_start,
        window_end=window_end,
        cluster_size=cluster_size,
        settings=settings,
    )
    return _Candidate(
        item=item,
        topic=topic,
        company=company,
        components=components,
        base_score=_base_score(components, settings),
    )


def apply_ranking(
    items: list[NewsItem],
    *,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    cluster_sizes: dict[str, int] | None = None,
    top_story_limit: int | None = None,
    settings: RankingSettings = DEFAULT_SETTINGS,
    debug: bool | None = None,
) -> tuple[list[NewsItem], list[RankedNews], RankingStats]:
    """Return ``items`` in final reading order plus their ranking records.

    The order and the records come from one pass, so the digest the caller
    stores and the ranks it stores can never disagree.
    """
    ranked, stats = rank_news(
        items,
        window_start=window_start,
        window_end=window_end,
        cluster_sizes=cluster_sizes,
        top_story_limit=top_story_limit,
        settings=settings,
    )
    by_id = {item.id: item for item in items}
    ordered = [by_id[entry.news_id] for entry in ranked]
    log_ranking(stats, debug=ranking_debug_enabled() if debug is None else debug)
    return ordered, ranked, stats


def format_ranking(stats: RankingStats, *, debug: bool = False) -> str:
    """The refresh summary, with a per-story breakdown in debug mode."""
    lines = [
        "Ranking:",
        f"Candidates: {stats.candidates}",
        f"Top stories: {stats.top_stories}",
        f"Topics: {stats.topics}",
        f"Companies: {stats.companies}",
    ]
    if debug:
        lines.append("")
        for entry in stats.ranked:
            lines.append(entry.describe())
    return "\n".join(lines)


def log_ranking(stats: RankingStats, *, debug: bool = False) -> None:
    """Log a one-line summary, plus per-story detail in debug mode."""
    if stats.candidates == 0:
        return
    logger.info(
        "ranking: candidates=%s top_stories=%s topics=%s companies=%s",
        stats.candidates,
        stats.top_stories,
        stats.topics,
        stats.companies,
    )
    if not debug:
        return
    for entry in stats.ranked:
        logger.info("ranking entry: %s", entry.describe())
