"""Event-level dedup: one story, one digest entry.

The rule layer in ``app.pipelines.dedup`` removes the same URL and byte-equal
titles. It cannot see that OpenAI announcing a model, TechCrunch reporting it
and 量子位 re-reporting it are one event told three ways, so the digest used to
show three near-identical rows.

This module adds a second, deliberately conservative layer on top. It is
deterministic and explainable: every merge carries the reason and the score
that produced it, so a wrong merge can be traced to one signal instead of a
model's opaque output. No embedding model, vector store or LLM call is
involved, which keeps a refresh cheap and reproducible.

False positives are the expensive mistake here: showing two real stories as one
silently hides news, while showing one story twice is merely untidy. Every
threshold therefore errs towards keeping items apart, and a merge normally
requires two independent signals to agree.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.config.sources import source_map
from app.models import NewsItem

logger = logging.getLogger(__name__)

# Official first-party news beats a lab's research post, which beats second-hand
# reporting. A lower rank wins, matching dedup.choose_winner. ``research`` is the
# class Phase 10.11 introduced in place of ``blog``.
SOURCE_TYPE_RANK = {"official": 0, "research": 1, "media": 2}
UNKNOWN_SOURCE_TYPE_RANK = 3

# Function words carry no event signal; keeping them would make every pair of
# English titles look slightly similar.
STOPWORDS = frozenset(
    {
        "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
        "at", "by", "as", "is", "are", "was", "were", "be", "been", "it", "its",
        "this", "that", "these", "those", "from", "into", "over", "after",
        "before", "than", "then", "new", "now", "how", "why", "what", "which",
        "who", "when", "where", "we", "our", "you", "your", "they", "their",
        "will", "can", "could", "should", "would", "may", "might", "must",
        "has", "have", "had", "do", "does", "did", "not", "but", "about",
        "more", "most", "less", "very", "just", "also", "up", "out", "all",
        "says", "said", "announces", "announced", "introducing", "release",
        "releases", "released", "update", "updates", "story", "news", "today",
    }
)

# A latin word is any run of letters, digits, dots and hyphens. Keeping dots and
# hyphens intact is what lets "gpt-6" and "v4.1" survive as single terms.
LATIN_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9._\-]*")
# CJK text has no spaces, so runs are matched and compared as character bigrams.
CJK_RUN_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")
# A model or version identifier: it must start with letters and contain a digit,
# so "gpt-6", "v4.1", "qwen3guard" and "k2.6" count while a bare "500m", "2026"
# or "5" does not. Numbers like valuations are not event identifiers, and
# treating them as such used to merge unrelated funding stories.
DISTINCTIVE_TERM_RE = re.compile(r"[a-z]+[a-z0-9]*[.\-]?[0-9][a-z0-9._\-]*")

# A calendar year is not event evidence: "2026" appears in unrelated stories and
# two of them sharing it says nothing. Model versions and figures are a
# different matter and are handled by DISTINCTIVE_TERM_RE and _figures.
YEAR_RE = re.compile(r"(?:19|20)\d{2}")

# Word pairs that describe opposite outcomes. Two items that each pick a
# different side of one pair ("fails" vs "passes a safety benchmark") are
# reporting contradictory results, not the same announcement, so they are never
# folded together. The list is intentionally short and high-confidence: an
# unknown pair simply stays unmerged and shows up as two entries.
OPPOSITE_PAIRS: tuple[tuple[frozenset[str], frozenset[str]], ...] = (
    (
        frozenset({"fail", "fails", "failed", "failure", "failing"}),
        frozenset({"pass", "passes", "passed", "passing", "succeed", "succeeds"}),
    ),
    (
        frozenset(
            {
                "drop", "drops", "dropped", "cut", "cuts", "lower", "lowers",
                "fall", "falls", "decrease",
            }
        ),
        frozenset(
            {
                "rise", "rises", "rose", "raise", "raises", "increase",
                "increases", "higher", "hike", "hikes",
            }
        ),
    ),
    (
        frozenset(
            {
                "launch", "launches", "launched", "release", "releases",
                "released", "ship", "ships", "available",
            }
        ),
        frozenset(
            {
                "deprecate", "deprecates", "deprecated", "retire", "retires",
                "retired", "shutdown", "shut", "sunset", "remove", "removes",
                "discontinue",
            }
        ),
    ),
    (
        frozenset({"approve", "approves", "approved", "allow", "allows", "allowed"}),
        frozenset(
            {
                "reject", "rejects", "rejected", "ban", "bans", "banned",
                "deny", "denies", "denied", "block", "blocks", "blocked",
            }
        ),
    ),
    (
        frozenset({"gain", "gains", "gained", "win", "wins", "won"}),
        frozenset({"lose", "loses", "lost", "losing"}),
    ),
    (
        frozenset({"open", "opens", "opened", "opening"}),
        frozenset({"close", "closes", "closed", "closing", "shut"}),
    ),
)


@dataclass(frozen=True)
class EventDedupSettings:
    """All event-dedup thresholds, kept in one place.

    ``max_hours_apart`` mirrors the 48h horizon the rule layer already uses for
    identical titles, so both layers agree on what "the same news cycle" means.
    """

    max_hours_apart: float = 48.0
    # Body similarity is the primary signal: a duplicate paraphrases the same
    # facts, while a follow-up story about the same subject does not. Required
    # unconditionally, which is what keeps "GPT-6 pricing drops" out of the
    # "GPT-6 is announced" cluster.
    body_min: float = 0.62
    # A headline this close is enough on its own, once the body agrees.
    title_min: float = 0.45
    # Cross-language coverage is the common case here: an English official post
    # and a Chinese report share almost no headline wording but do share the
    # model name, so a shared identifier lowers the headline bar.
    title_min_with_shared_term: float = 0.30
    # With no body text at all the headline is the only evidence, so it must be
    # an almost exact match (the rule layer already removes byte-equal titles).
    title_exact_threshold: float = 0.90
    # Second route, for a story told in two languages. "Mecka AI nears 500M
    # valuation" and its Chinese translation agree on almost every headline word
    # and on the figure, but their summaries only loosely overlap because each
    # paraphrases the fact differently. When the headline is this close *and*
    # the two name the same figure, a weaker body match is enough.
    title_relaxed_min: float = 0.70
    body_min_with_shared_figure: float = 0.45


DEFAULT_SETTINGS = EventDedupSettings()

# Source name -> configured priority, used only to order sources of the same
# class (OpenAI before Anthropic, say). Names are what NewsItem carries.
def _source_priorities() -> dict[str, int]:
    return {source.name: source.priority for source in source_map().values()}


def _tokens(text: str) -> set[str]:
    """Comparable tokens: latin words, numbers, plus CJK character bigrams.

    Numbers are kept at any length because they often carry the distinction
    between two otherwise identical headlines ("GPT-5" vs "GPT-6", a roundup
    part 1 vs part 2). Dropping them would make unrelated stories look alike.
    """
    lowered = str(text or "").lower()
    tokens: set[str] = set()
    for match in LATIN_TOKEN_RE.finditer(lowered):
        token = match.group(0).strip("._-")
        if not token:
            continue
        if token.isdigit():
            tokens.add(token)
            continue
        if len(token) < 2 or token in STOPWORDS:
            continue
        tokens.add(token)
    for run in CJK_RUN_RE.findall(lowered):
        if len(run) == 1:
            tokens.add(run)
            continue
        tokens.update(run[index : index + 2] for index in range(len(run) - 1))
    return tokens


def _distinctive_terms(text: str) -> set[str]:
    """Model and version identifiers, the strongest cross-language signal."""
    return {match.group(0) for match in DISTINCTIVE_TERM_RE.finditer(str(text or "").lower())}


def _version_tokens(text: str) -> set[str]:
    """Tokens that carry a number, such as ``gpt-6``, ``v4.1`` or ``500m``.

    Two titles that each name a *different* number are almost always two
    different events ("GPT-5" vs "GPT-6", a 500M round vs an 800M one), so a
    disjoint pair of these blocks a merge outright.
    """
    return {token for token in _tokens(text) if any(char.isdigit() for char in token)}


def _figures(text: str) -> set[str]:
    """Quantities shared by two reports of one fact, ignoring calendar years.

    A round size ("500m"), a price cut or a benchmark number is part of what
    makes a story a story. A year is not: "2026" turns up in unrelated
    headlines, so it is excluded rather than allowed to look like agreement.
    """
    return {token for token in _version_tokens(text) if not YEAR_RE.fullmatch(token)}


def _substantive_figures(figures: set[str]) -> set[str]:
    """Figures specific enough to be evidence on their own.

    A bare number can coincide by accident, so the relaxed route needs at least
    one quantity that also carries a unit or a name ("500m", "gpt-6", "v4.1").
    Two items that only share "5", "500" or "3.5" do not qualify.
    """
    return {token for token in figures if any(char.isalpha() for char in token)}


def _has_opposite_stance(left: str, right: str) -> bool:
    """True when the two texts assert opposite sides of a known outcome pair."""
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    for positive, negative in OPPOSITE_PAIRS:
        if (left_tokens & positive and right_tokens & negative) or (
            left_tokens & negative and right_tokens & positive
        ):
            return True
    return False


def _dice(left: set[str], right: set[str]) -> float:
    """Sørensen-Dice overlap of two token sets, in ``0..1``."""
    if not left or not right:
        return 0.0
    return 2 * len(left & right) / (len(left) + len(right))


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
class EventMatch:
    """Why two items were judged to describe the same event."""

    reason: str
    score: float
    title_similarity: float
    shared_terms: tuple[str, ...] = ()
    hours_apart: float | None = None

    def describe(self) -> str:
        parts = [f"reason={self.reason}", f"score={self.score:.2f}"]
        if self.shared_terms:
            parts.append(f"shared={','.join(self.shared_terms)}")
        if self.hours_apart is not None:
            parts.append(f"hours_apart={self.hours_apart:.1f}")
        return " ".join(parts)


def match_event(
    left: NewsItem,
    right: NewsItem,
    settings: EventDedupSettings = DEFAULT_SETTINGS,
) -> EventMatch | None:
    """Return why ``left`` and ``right`` are one event, or ``None``.

    Only the text and timestamps are used, never the source, so the same
    decision applies however the pair was collected.
    """
    left_at = _published_at(left)
    right_at = _published_at(right)
    if left_at is None or right_at is None:
        # An undated article cannot be placed in an event: keep it separate.
        return None
    hours_apart = abs((left_at - right_at).total_seconds()) / 3600
    if hours_apart > settings.max_hours_apart:
        return None

    left_text = f"{left.title_original} {left.title_cn}"
    right_text = f"{right.title_original} {right.title_cn}"
    left_body = f"{left.summary} {left.why_it_matters}"
    right_body = f"{right.summary} {right.why_it_matters}"

    # Two items naming different versions are different events ("GPT-5" vs
    # "GPT-6", a 500M round vs an 800M one). This gate runs first so no amount
    # of textual overlap can override it.
    left_versions = _version_tokens(left_text) | _version_tokens(left_body)
    right_versions = _version_tokens(right_text) | _version_tokens(right_body)
    if left_versions and right_versions and left_versions.isdisjoint(right_versions):
        return None
    # Contradictory outcomes ("fails" vs "passes", "drops" vs "rises") are a
    # second story about the same subject, never the same announcement.
    if _has_opposite_stance(f"{left_text} {left_body}", f"{right_text} {right_body}"):
        return None

    title_similarity = _dice(_tokens(left_text), _tokens(right_text))
    body_similarity = _dice(_tokens(left_body), _tokens(right_body))
    shared = tuple(sorted(_distinctive_terms(left_text) & _distinctive_terms(right_text)))
    figures = _figures(f"{left_text} {left_body}") & _figures(
        f"{right_text} {right_body}"
    )

    if not left_body.strip() or not right_body.strip():
        # Two bare headlines: the headline is the only evidence available.
        if title_similarity < settings.title_exact_threshold:
            return None
        # A near-identical headline is still only "probably the same", so a
        # shared identifier is required to reach a confident merge score.
        if not shared:
            return None
        score = title_similarity
        return EventMatch(
            reason="title_similarity",
            score=score,
            title_similarity=title_similarity,
            shared_terms=shared,
            hours_apart=hours_apart,
        )

    if body_similarity < settings.body_min:
        # A story translated between two languages paraphrases the same fact in
        # different words, so its summaries overlap less than two reports in one
        # language would. The headline and the shared figure have to agree
        # unusually well for this weaker body bar, which keeps follow-up stories
        # ("GPT-6 pricing drops") out of the announcement they follow.
        close_enough_title = title_similarity >= settings.title_relaxed_min
        strong_figures = _substantive_figures(figures)
        if (
            body_similarity < settings.body_min_with_shared_figure
            or not close_enough_title
            or not strong_figures
        ):
            return None
        return EventMatch(
            reason="same_headline_and_figure",
            score=(title_similarity + body_similarity) / 2,
            title_similarity=title_similarity,
            shared_terms=tuple(sorted(strong_figures)),
            hours_apart=hours_apart,
        )
    title_floor = (
        settings.title_min_with_shared_term if shared else settings.title_min
    )
    if title_similarity < title_floor:
        return None
    score = (title_similarity + body_similarity) / 2
    return EventMatch(
        reason="shared_term_text_similarity" if shared else "text_similarity",
        score=score,
        title_similarity=title_similarity,
        shared_terms=shared,
        hours_apart=hours_apart,
    )


def _completeness(item: NewsItem) -> int:
    """How much text a digest entry would show, used to break ties."""
    return len(item.summary or "") + len(item.why_it_matters or "")


def _winner_key(item: NewsItem, priorities: dict[str, int]) -> tuple:
    rank = SOURCE_TYPE_RANK.get(item.source_type, UNKNOWN_SOURCE_TYPE_RANK)
    priority = priorities.get(item.source, 1000)
    importance = item.importance_score if item.importance_score is not None else -1
    published = _published_at(item) or datetime.max.replace(tzinfo=timezone.utc)
    return (rank, priority, -importance, -_completeness(item), published, item.id)


def choose_main_news(
    cluster: list[NewsItem],
    settings: EventDedupSettings = DEFAULT_SETTINGS,
) -> NewsItem:
    """Pick the entry that represents a cluster.

    Order of preference: source class (official > research > media), the
    source's configured priority, a higher ``importance_score``, a fuller summary, the
    earliest publication (the original announcement), and finally the id so the
    result never depends on collection order.
    """
    priorities = _source_priorities()
    return min(cluster, key=lambda item: _winner_key(item, priorities))


@dataclass
class EventDedupDecision:
    """One cluster: the entry kept, and the duplicates folded into it."""

    kept: NewsItem
    merged: list[tuple[NewsItem, EventMatch]] = field(default_factory=list)


@dataclass
class EventDedupStats:
    candidates: int = 0
    clusters: int = 0
    merged: int = 0
    decisions: list[EventDedupDecision] = field(default_factory=list)
    # Every surviving entry's id mapped to the size of the cluster it represents.
    # A story two independent outlets reported is corroborated, which the ranker
    # treats as a small importance signal. Kept here because clustering is the
    # only place that knows the answer, and re-deriving it later would mean
    # clustering twice.
    cluster_sizes: dict[str, int] = field(default_factory=dict)

    @property
    def reduced(self) -> bool:
        return self.merged > 0


def dedupe_events(
    items: list[NewsItem],
    settings: EventDedupSettings = DEFAULT_SETTINGS,
) -> tuple[list[NewsItem], EventDedupStats]:
    """Fold items describing one event into a single digest entry.

    Clustering is greedy over a deterministic order and compares a candidate
    against every member of an existing cluster, so a chain of reports about one
    event still collapses to one entry. The returned order follows the input so
    a digest keeps the ordering its caller established. Nothing is deleted: the
    caller decides what to link, and every article stays in ``news_articles``.
    """
    stats = EventDedupStats(candidates=len(items))
    if not items:
        return [], stats

    clusters: list[list[NewsItem]] = []
    # Parallel to ``clusters``: entry 0 of each cluster is the seed and has no
    # justifying match, every later member carries the one that admitted it.
    matches: list[list[EventMatch | None]] = []
    # Clustering walks a deterministic order so the result never depends on how
    # the sources happened to be iterated, but the output below restores the
    # caller's order.
    for item in sorted(items, key=lambda entry: entry.id):
        for index, cluster in enumerate(clusters):
            found = None
            for member in cluster:
                candidate = match_event(item, member, settings)
                if candidate is not None:
                    found = candidate
                    break
            if found is not None:
                cluster.append(item)
                matches[index].append(found)
                break
        else:
            clusters.append([item])
            matches.append([None])

    winners_by_id: dict[str, NewsItem] = {}
    for cluster, cluster_matches in zip(clusters, matches):
        winner = choose_main_news(cluster, settings)
        decision = EventDedupDecision(kept=winner)
        for member, match in zip(cluster, cluster_matches):
            if member is winner:
                continue
            decision.merged.append((member, _justify(member, winner, match, settings)))
        stats.merged += len(decision.merged)
        if decision.merged:
            stats.decisions.append(decision)
        for member in cluster:
            winners_by_id[member.id] = winner

    stats.clusters = len(clusters)
    # Walk the input once, emitting each cluster's winner where its first
    # member appeared and skipping every folded duplicate.
    kept: list[NewsItem] = []
    emitted: set[str] = set()
    for item in items:
        winner = winners_by_id.get(item.id, item)
        if winner.id in emitted:
            continue
        emitted.add(winner.id)
        kept.append(winner)
    for member_ids, winner in winners_by_id.items():
        stats.cluster_sizes[winner.id] = stats.cluster_sizes.get(winner.id, 0) + 1
    return kept, stats


def _justify(
    member: NewsItem,
    winner: NewsItem,
    match: EventMatch | None,
    settings: EventDedupSettings,
) -> EventMatch:
    """The reason a cluster member is folded into the entry it is folded into.

    ``match`` is the evidence that admitted ``member`` into the cluster, which
    normally points at an earlier member rather than the winner. When the
    winner arrived later the member is the cluster seed and carries no match at
    all; the same relation is then re-derived against the winner directly.
    """
    if match is not None:
        return match
    recovered = match_event(member, winner, settings)
    if recovered is not None:
        return recovered
    # Reachable only if the winner matched a third item but not this one, which
    # the symmetric rule should prevent. Recorded rather than hidden so a
    # surprise surfaces in the debug view instead of looking like a match.
    logger.debug(
        "cluster member folded without a direct match member=%s winner=%s",
        member.id,
        winner.id,
    )
    return EventMatch(reason="transitive_cluster", score=0.0, title_similarity=0.0)


def format_event_dedup(decision: EventDedupDecision) -> str:
    """Debug view of one cluster, e.g. ``KEEP OpenAI: ... / MERGE ...``."""
    lines = [f"KEEP {decision.kept.source}: {decision.kept.title_cn or decision.kept.title_original}"]
    for item, match in decision.merged:
        lines.append(f"MERGE {item.source}: {item.title_cn or item.title_original}")
        lines.append(f"  {match.describe()}")
    return "\n".join(lines)


def log_event_dedup(stats: EventDedupStats, *, debug: bool = False) -> None:
    """Log a one-line summary, plus per-cluster detail in debug mode."""
    if stats.candidates == 0:
        return
    logger.info(
        "event dedup: candidates=%s clusters=%s merged=%s",
        stats.candidates,
        stats.clusters,
        stats.merged,
    )
    if not debug:
        return
    for decision in stats.decisions:
        logger.info("event dedup decision:\n%s", format_event_dedup(decision))
