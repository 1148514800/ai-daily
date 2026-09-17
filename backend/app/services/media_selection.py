"""Keep the digest's second-hand reporting to a curated few.

Ranking only reorders, so before this phase every collected media story reached
the digest no matter how routine it was: a vendor's own announcement and the
twentieth write-up about it were both linked. The digest is meant to be a
first-party brief, so media is now *selected* rather than merely sorted last.

Three rules, all data-driven, all deterministic:

* a media story needs a real ``importance_score`` at or above the threshold —
  an un-enriched article has no claimed importance and does not get in on a
  fallback score;
* at most ``max_total`` media stories per digest, so the tail cannot be filled
  by the press;
* at most ``max_per_source`` from any one outlet, so one busy newsroom cannot
  occupy the slots on its own.

``official`` and ``research`` sources are exempt from every rule: the quantity
limits exist to bound *second-hand* volume, and applying them to a vendor's own
release would silence the very thing the digest is for.

Selection is not deletion. Unselected articles stay in ``news_articles`` and
remain searchable; only the digest-to-news link is skipped, so a later refresh
or a rebuild can pick them up again.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.models import NewsItem

logger = logging.getLogger(__name__)

MEDIA_DEBUG_ENV = "AI_DAILY_DEBUG_MEDIA_SELECTION"

# The one source class these rules apply to. Everything else is exempt, which
# is stated here rather than hard-coded at each check so the exemption reads as
# a decision ("only media is capped") instead of as an accident.
MEDIA_SOURCE_TYPE = "media"

# Why a candidate did or did not make it, reported in the debug view.
REASON_KEPT = "kept"
REASON_BELOW_THRESHOLD = "importance<{threshold}"
REASON_MISSING_IMPORTANCE = "importance is unknown"
REASON_PER_SOURCE_CAP = "per_source_cap"
REASON_TOTAL_CAP = "total_cap"


@dataclass(frozen=True)
class MediaSelectionSettings:
    """Every media rule, in one place.

    ``min_importance`` is compared against the LLM's ``importance_score``; a
    ``None`` score never qualifies, because a fallback number is what the
    pipeline uses when it has no judgement at all.
    """

    min_importance: int = 60
    max_total: int = 5
    max_per_source: int = 2


DEFAULT_SETTINGS = MediaSelectionSettings()


def media_debug_enabled() -> bool:
    """Per-candidate selection logging, opt-in so default logs stay short."""
    return os.getenv(MEDIA_DEBUG_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _published_key(item: NewsItem) -> datetime:
    """A comparable publish time; an unreadable one sorts as the oldest."""
    raw = item.published_at or ""
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _ordered_candidates(eligible: list[NewsItem]) -> list[NewsItem]:
    """Best-first ordering: importance, then recency, then id.

    Three stable sorts applied least-significant first, which is easier to read
    than one clever composite key and cannot mis-order an unparseable timestamp.
    Among two media stories the pipeline judged equally important, the newer one
    is the better use of a limited slot; the id ends the comparison so two
    candidates that agree on everything still produce one fixed order.
    """
    ordered = sorted(eligible, key=lambda item: item.id)
    ordered.sort(key=_published_key, reverse=True)
    ordered.sort(
        key=lambda item: item.importance_score if item.importance_score is not None else -1,
        reverse=True,
    )
    return ordered


@dataclass
class MediaDecision:
    """What happened to one media candidate, and why."""

    source: str
    title: str
    importance: int | None
    reason: str

    @property
    def kept(self) -> bool:
        return self.reason == REASON_KEPT

    def describe(self) -> str:
        importance = "--" if self.importance is None else f"{self.importance:02d}"
        action = "KEEP" if self.kept else "DROP"
        if self.kept:
            return f"{action} {self.source} | {self.title} | importance={importance}"
        return f"{action} {self.source} | {self.title} | reason={self.reason}"


@dataclass
class MediaSelectionStats:
    """The counts the refresh summary and the debug view report."""

    candidates: int = 0
    below_threshold: int = 0
    dropped_per_source: int = 0
    dropped_total: int = 0
    selected: int = 0
    decisions: list[MediaDecision] = field(default_factory=list)

    @property
    def dropped(self) -> int:
        return self.below_threshold + self.dropped_per_source + self.dropped_total


def select_media_articles(
    items: list[NewsItem],
    settings: MediaSelectionSettings = DEFAULT_SETTINGS,
) -> tuple[list[NewsItem], MediaSelectionStats]:
    """Drop the media stories that do not earn a place, keeping input order.

    Every ``official`` / ``research`` item is kept unconditionally. Media
    candidates are ranked by ``importance_score``, then by recency, then by id,
    and taken greedily while both caps allow it, so which stories survive does
    not depend on the order the collector happened to return them in.
    """
    stats = MediaSelectionStats()
    media = [item for item in items if item.source_type == MEDIA_SOURCE_TYPE]
    stats.candidates = len(media)
    if not media:
        return list(items), stats

    threshold_reason = REASON_BELOW_THRESHOLD.format(threshold=settings.min_importance)
    eligible: list[NewsItem] = []
    for item in media:
        if item.importance_score is None:
            stats.decisions.append(
                MediaDecision(item.source, item.title_cn or item.title_original, None, REASON_MISSING_IMPORTANCE)
            )
            continue
        if item.importance_score < settings.min_importance:
            stats.decisions.append(
                MediaDecision(
                    item.source,
                    item.title_cn or item.title_original,
                    item.importance_score,
                    threshold_reason,
                )
            )
            continue
        eligible.append(item)

    stats.below_threshold = len(media) - len(eligible)
    eligible = _ordered_candidates(eligible)

    kept_ids: set[str] = set()
    per_source: dict[str, int] = {}
    for item in eligible:
        used = per_source.get(item.source, 0)
        if used >= settings.max_per_source:
            stats.dropped_per_source += 1
            stats.decisions.append(
                MediaDecision(
                    item.source, item.title_cn or item.title_original, item.importance_score, REASON_PER_SOURCE_CAP
                )
            )
            continue
        if len(kept_ids) >= settings.max_total:
            stats.dropped_total += 1
            stats.decisions.append(
                MediaDecision(
                    item.source, item.title_cn or item.title_original, item.importance_score, REASON_TOTAL_CAP
                )
            )
            continue
        kept_ids.add(item.id)
        per_source[item.source] = used + 1
        stats.decisions.append(
            MediaDecision(item.source, item.title_cn or item.title_original, item.importance_score, REASON_KEPT)
        )

    stats.selected = len(kept_ids)
    # The caller's order is restored, so event dedup, ranking and the digest all
    # keep reading the list in one consistent sequence.
    return [item for item in items if item.source_type != MEDIA_SOURCE_TYPE or item.id in kept_ids], stats


def format_media_selection(stats: MediaSelectionStats, *, debug: bool = False) -> str:
    """The refresh summary, with a per-candidate breakdown in debug mode."""
    lines = [
        "Media selection",
        f"Candidates: {stats.candidates}",
        f"Below importance threshold: {stats.below_threshold}",
        f"Dropped by per-source cap: {stats.dropped_per_source}",
        f"Dropped by total cap: {stats.dropped_total}",
        f"Selected: {stats.selected}",
    ]
    if debug:
        lines.append("")
        lines.extend(decision.describe() for decision in stats.decisions)
    return "\n".join(lines)


def log_media_selection(stats: MediaSelectionStats, *, debug: bool = False) -> None:
    """Log a one-line summary, plus per-candidate detail in debug mode."""
    if stats.candidates == 0:
        return
    logger.info(
        "media selection: candidates=%s below_threshold=%s dropped_per_source=%s "
        "dropped_total=%s selected=%s",
        stats.candidates,
        stats.below_threshold,
        stats.dropped_per_source,
        stats.dropped_total,
        stats.selected,
    )
    if not debug:
        return
    for decision in stats.decisions:
        logger.info("media selection entry: %s", decision.describe())
