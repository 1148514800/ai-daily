"""Turn a web search into extra candidates for the digest, without trusting it.

The fixed sources are the trunk of AI Daily: curated, first-party where
possible, and each one a single feed whose failure is contained. What they
cannot do is *discover* — a model released by a lab nobody configured, a robotics
story on an outlet that is not on the list, a breaking event that no configured
feed has picked up yet. This module fills that gap with a search provider
(``app/collectors/tavily.py``) and stops there.

The output is candidates, not news. Everything discovered here is handed to the
same pipeline as a fixed source's article — the same issue window, the same rule
dedup, the same article extraction, the same LLM importance, the same media
selection, the same ranking. Discovery changes *what the pipeline is offered*; it
never changes what the pipeline decides, and it has no privilege anywhere in it.

That places three duties on this module.

**Distrust the provider about time.** ``time_range=day`` is a request, not a
guarantee, and the benchmark's 84/84 was one observation. Every hit is checked
locally against ``now - 24h < published_at <= now``, and a hit without a
timestamp is dropped rather than guessed at: discovery is a supplement to a
digest that already has content, so it does not need to buy recall with pages
whose age is unknown.

**Do not let one query or one domain decide the ranking.** The provider's own
``score`` is not comparable between queries — measured across one benchmark run
it ranged from 0.88 to 0.01 for results of similar value — so it is kept for
diagnosis and never sorted on. Candidates are ranked by Reciprocal Rank Fusion
over the *other* queries that found the same URL: a page two different topic
queries both returned is a better hot-story signal than a page one query ranked
first. A domain cap then stops a portal that ranks well on every query from
taking the whole allowance.

**Never break the digest.** Every failure — a rejected key, a rate limit, an
outage, a schema change, or all ten queries failing — is reported and produces an
empty result. The fixed sources are collected regardless, and a refresh whose
discovery layer failed is still a normal refresh.

The gates run in the order the funnel is described in: provider hit -> rolling
24h -> AI relevance -> URL dedup -> RRF -> per-domain cap -> candidate cap. Each
stage that drops something counts it, so ``DiscoveryStats`` explains exactly where
the ~90 raw hits went.
"""

from __future__ import annotations

import logging
import os
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, Sequence

from app.collectors import tavily
from app.collectors.raw import CollectResult, RawArticle
from app.config.discovery import (
    DISCOVERY_QUERIES,
    NON_ARTICLE_DOMAINS,
    RRF_K,
    WebDiscoverySettings,
    load_web_discovery_settings,
)
from app.config.sources import (
    domain_of,
    known_source_domains,
    source_for_domain,
)
from app.pipelines.ai_filter import is_ai_related
from app.pipelines.urls import canonicalize_url
from app.services.digest_window import as_utc

logger = logging.getLogger(__name__)

# Identifies the discovery layer in the refresh report. Deliberately not a
# configured source id: the report shows it as one block, and the coverage
# section skips it, because Tavily is a way of collecting and not an official
# company channel.
DISCOVERY_SOURCE_ID = "web-discovery-tavily"
DISCOVERY_SOURCE_NAME = "Tavily Web Discovery"

# Web Discovery results are second-hand by default. A domain that matches a
# configured source reuses that source's own ``source_type``; anything else is
# ``media``, never ``official``. A search engine saying a page exists says
# nothing about who published it, and promoting an unknown host to a first-party
# vendor on the provider's word is precisely the mistake that would corrupt the
# ranking. A site worth tracking long-term earns a place in ``sources.py``
# instead.
UNKNOWN_SOURCE_TYPE = "media"


@dataclass
class DiscoveryCandidate:
    """One URL discovered by search, with what the ranking needs.

    Internal: never returned by the API and never stored. ``matched_queries`` and
    ``query_ranks`` are index-aligned — the rank is where this URL sat in that
    query's own result list, which is the only per-query signal RRF uses.
    """

    title: str = ""
    url: str = ""
    canonical_url: str = ""
    domain: str = ""

    snippet: str = ""
    published_at: datetime | None = None

    matched_queries: list[str] = field(default_factory=list)
    query_ranks: list[int] = field(default_factory=list)

    provider_score: str = ""
    rrf_score: float = 0.0

    @property
    def hits(self) -> int:
        """How many distinct queries returned this URL."""
        return len(self.query_ranks)


@dataclass
class DiscoveryStats:
    """Where the funnel lost candidates. Printed once per refresh.

    The counters are per *provider hit* until dedup and per *unique URL* after
    it, which is the only reading that makes the funnel add up: the 24h and AI
    gates see the raw list, while the domain and candidate caps see the merged
    one.
    """

    queries: int = 0
    successful_queries: int = 0
    failed_queries: int = 0

    raw_results: int = 0
    inside_24h: int = 0

    dropped_missing_time: int = 0
    dropped_outside_window: int = 0
    dropped_not_ai: int = 0
    dropped_social: int = 0

    unique_urls: int = 0
    matched_multiple_queries: int = 0
    dropped_domain_cap: int = 0
    dropped_candidate_cap: int = 0

    selected: int = 0

    def summary_line(self) -> str:
        """The one line a normal refresh logs."""
        return (
            f"Web discovery: queries={self.queries} ok={self.successful_queries} "
            f"raw={self.raw_results} recent={self.inside_24h} "
            f"unique={self.unique_urls} selected={self.selected}"
        )


@dataclass
class DiscoveryOutcome:
    """Everything one discovery run produced."""

    report: CollectResult
    stats: DiscoveryStats
    candidates: list[DiscoveryCandidate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# gates
# --------------------------------------------------------------------------- #


def is_within_last_24h(moment: datetime | None, now: datetime) -> bool:
    """Whether ``moment`` falls in the rolling window ``now - 24h < t <= now``.

    A future timestamp is never "recent": clock skew and pre-dated pages would
    otherwise satisfy an age test. This gate decides whether a *candidate* is
    worth feeding the pipeline at all; which digest a survivor belongs to is
    still decided by the issue window alone.
    """
    if moment is None:
        return False
    current = as_utc(now)
    published = as_utc(moment)
    if published > current:
        return False
    return current - published < timedelta(hours=24)


def is_non_article_surface(domain: str) -> bool:
    """Whether a hostname is a social surface the extractor cannot read.

    Only structurally-not-an-article pages are rejected here, and the list is
    deliberately tiny. Portals, aggregators and personal blogs are left in:
    whether they deserve a place is a question for importance, media selection
    and ranking, and a discovery layer that answered it itself would be a second,
    worse source configuration.
    """
    if not domain:
        return False
    return any(domain == name or domain.endswith(f".{name}") for name in NON_ARTICLE_DOMAINS)


def candidate_from_hit(hit: tavily.TavilyHit) -> DiscoveryCandidate:
    """A provider hit as a candidate, with the domain taken from its URL.

    The hostname always comes from the URL and never from anything the provider
    calls a site name. The Aliyun probe had to learn this the hard way: its
    ``hostname`` is a display name such as "云栖大会", and reading it as a host
    silently corrupts every count downstream.
    """
    url = hit.url.strip()
    canonical = canonicalize_url(url)
    domain = domain_of(url) or domain_of(canonical)
    return DiscoveryCandidate(
        title=hit.title.strip(),
        url=url,
        canonical_url=canonical,
        domain=domain,
        snippet=hit.snippet.strip(),
        published_at=tavily.published_at(hit.published),
        provider_score=hit.score,
    )


# --------------------------------------------------------------------------- #
# ranking and selection
# --------------------------------------------------------------------------- #


def rrf_contribution(rank: int, *, k: int = RRF_K) -> float:
    """``1 / (k + rank)`` for one 1-based rank.

    The constant damps the top of the list so that agreeing across queries beats
    a single strong rank, which is the whole reason for fusing instead of sorting
    by any one query's score.
    """
    return 1.0 / (k + rank)


def fuse(candidates: Sequence[DiscoveryCandidate], *, k: int = RRF_K) -> None:
    """Set each candidate's RRF score from the queries that returned it.

    In place, because the score is derived data and a second list would just be
    another thing to keep in step.
    """
    for candidate in candidates:
        candidate.rrf_score = sum(rrf_contribution(rank, k=k) for rank in candidate.query_ranks)


def rank_key(candidate: DiscoveryCandidate) -> tuple:
    """The deterministic order: RRF, then recency, then the URL.

    ``canonical_url`` is the final tie-break, so two candidates that fuse to the
    same score and share a timestamp still have one stable order. The provider's
    ``score`` appears nowhere: measured across one benchmark run it was not
    comparable between queries, and letting it in would make the order depend on
    which query happened to rank a page highly.
    """
    published = as_utc(candidate.published_at) if candidate.published_at else None
    stamp = published.timestamp() if published is not None else 0.0
    return (-candidate.rrf_score, -stamp, candidate.canonical_url, candidate.url)


def select_candidates(
    candidates: Sequence[DiscoveryCandidate],
    *,
    max_per_domain: int,
    max_candidates: int,
) -> tuple[list[DiscoveryCandidate], int, int]:
    """Apply the domain cap and the final cap to an already-ranked list.

    Returns ``(selected, dropped_for_domain, dropped_for_cap)``. Iterating in
    rank order means the cap keeps the *best* page of each hostname, and the
    domain cap is a soft pre-selection for one run rather than a blacklist:
    nothing is remembered between refreshes.
    """
    selected: list[DiscoveryCandidate] = []
    per_domain: Counter = Counter()
    dropped_domain = 0
    dropped_cap = 0
    for candidate in candidates:
        if per_domain[candidate.domain] >= max_per_domain:
            dropped_domain += 1
            continue
        if len(selected) >= max_candidates:
            dropped_cap += 1
            continue
        per_domain[candidate.domain] += 1
        selected.append(candidate)
    return selected, dropped_domain, dropped_cap


# --------------------------------------------------------------------------- #
# conversion
# --------------------------------------------------------------------------- #


def to_raw_article(candidate: DiscoveryCandidate, known: frozenset[str] | None = None) -> RawArticle:
    """A selected candidate as the ``RawArticle`` the pipeline already consumes.

    A hostname that belongs to a configured source reuses that source's id, name
    and ``source_type``. That is what lets the same story arriving from Tavily and
    from the vendor's own feed merge instead of duplicating — and it keeps the
    first-party class the project decided on, rather than a guess made from a
    search result. Everything else is ``media`` under a ``web:<domain>`` id.
    """
    lookup = known if known is not None else known_source_domains()
    source = source_for_domain(candidate.domain)
    if source is not None:
        source_id = source.id
        source_name = source.name
        source_type = source.source_type
    else:
        source_id = f"web:{candidate.domain}"
        source_name = candidate.domain
        source_type = UNKNOWN_SOURCE_TYPE

    return RawArticle(
        source_id=source_id,
        source=source_name,
        source_type=source_type,
        title=candidate.title,
        url=candidate.url,
        canonical_url=candidate.canonical_url,
        published_at=candidate.published_at,
        # The search snippet is the only text this layer has. Article extraction
        # runs later and replaces it with the real body; until then it is what
        # the LLM would see if extraction failed, which is exactly what a fixed
        # source's feed summary is for.
        summary=candidate.snippet,
    )


# --------------------------------------------------------------------------- #
# the run
# --------------------------------------------------------------------------- #


def _log_drop(reason: str, candidate: DiscoveryCandidate) -> None:
    logger.info(
        "DROP reason=%s domain=%s title=%s url=%s",
        reason,
        candidate.domain or "-",
        candidate.title[:80] or "-",
        candidate.url,
    )


def _log_keep(candidate: DiscoveryCandidate) -> None:
    logger.info(
        "KEEP rrf=%.6f hits=%s domain=%s title=%s url=%s",
        candidate.rrf_score,
        candidate.hits,
        candidate.domain or "-",
        candidate.title[:80] or "-",
        candidate.url,
    )


def collect_web_discovery(
    now: datetime | None = None,
    *,
    settings: WebDiscoverySettings | None = None,
    queries: Sequence[str] = DISCOVERY_QUERIES,
    send: Callable[[str, dict, dict, float], tavily.Attempt] | None = None,
) -> DiscoveryOutcome | None:
    """Run one discovery pass. ``None`` when web discovery is switched off.

    ``None`` rather than an empty result is the point: a deployment with
    ``WEB_DISCOVERY_ENABLED=false`` must behave exactly as it did before this
    module existed, with no discovery entry in the report and no request made.
    """
    config = settings or load_web_discovery_settings()
    if not config.enabled:
        return None

    if not config.api_key:
        # Enabled but not configured. Reported once, then skipped: a
        # configuration mistake must not fail a refresh that is otherwise fine.
        logger.warning(
            "web discovery is enabled but TAVILY_API_KEY is missing; skipping discovery"
        )
        return DiscoveryOutcome(
            report=CollectResult(
                source_id=DISCOVERY_SOURCE_ID,
                source_name=DISCOVERY_SOURCE_NAME,
                success=False,
                error="TAVILY_API_KEY is not configured",
                discovery=True,
            ),
            stats=DiscoveryStats(queries=len(queries)),
            errors=["TAVILY_API_KEY is not configured"],
        )

    if config.provider not in ("tavily",):
        logger.warning(
            "web discovery provider %r is not implemented; skipping discovery",
            config.provider,
        )
        return DiscoveryOutcome(
            report=CollectResult(
                source_id=DISCOVERY_SOURCE_ID,
                source_name=DISCOVERY_SOURCE_NAME,
                success=False,
                error=f"provider {config.provider!r} is not implemented",
                discovery=True,
            ),
            stats=DiscoveryStats(queries=len(queries)),
            errors=[f"provider {config.provider!r} is not implemented"],
        )

    transport = send or tavily.send_request
    current = as_utc(now or datetime.now(timezone.utc))
    headers = tavily.auth_headers(config.api_key)
    known = known_source_domains()
    stats = DiscoveryStats(queries=len(queries))
    errors: list[str] = []
    kept: list[DiscoveryCandidate] = []

    for query in queries:
        payload = tavily.build_payload(query, max_results=config.results_per_query)
        attempt = transport(tavily.ENDPOINT, headers, payload, config.timeout)
        if attempt.status_code != 200 or not attempt.parsed:
            stats.failed_queries += 1
            errors.append(f"{query}: {tavily.describe_failure(attempt)}")
            continue

        parsed = tavily.parse_search_response(attempt.payload)
        if not parsed.found:
            stats.failed_queries += 1
            errors.append(f"{query}: {tavily.describe_failure(attempt)}")
            continue

        stats.successful_queries += 1
        for rank, hit in enumerate(parsed.hits, start=1):
            stats.raw_results += 1
            candidate = candidate_from_hit(hit)

            if is_non_article_surface(candidate.domain):
                stats.dropped_social += 1
                if config.debug:
                    _log_drop("social", candidate)
                continue

            if candidate.published_at is None:
                stats.dropped_missing_time += 1
                if config.debug:
                    _log_drop("missing_time", candidate)
                continue

            if not is_within_last_24h(candidate.published_at, current):
                stats.dropped_outside_window += 1
                if config.debug:
                    _log_drop("outside_24h", candidate)
                continue

            stats.inside_24h += 1

            if not is_ai_related(candidate.title, candidate.snippet):
                stats.dropped_not_ai += 1
                if config.debug:
                    _log_drop("not_ai", candidate)
                continue

            # The rank is the position in *this* query's list, which is what RRF
            # needs; a URL listed twice by one query still contributes once.
            candidate.query_ranks = [rank]
            candidate.matched_queries = [query]
            kept.append(candidate)

    # Missing every query is not an error the refresh should absorb silently, but
    # it is also not fatal: the fixed sources are collected either way.
    if stats.successful_queries == 0:
        error = "; ".join(errors) or "every query failed"
        logger.warning("web discovery failed: %s", error)
        return DiscoveryOutcome(
            report=CollectResult(
                source_id=DISCOVERY_SOURCE_ID,
                source_name=DISCOVERY_SOURCE_NAME,
                success=False,
                error=error,
                discovery=True,
            ),
            stats=stats,
            errors=errors,
        )

    merged = _merge_by_url(kept)
    fuse(merged)
    merged.sort(key=rank_key)
    stats.matched_multiple_queries = sum(1 for candidate in merged if candidate.hits > 1)
    stats.unique_urls = len(merged)

    selected, dropped_domain, dropped_cap = select_candidates(
        merged,
        max_per_domain=config.max_per_domain,
        max_candidates=config.max_candidates,
    )
    stats.dropped_domain_cap = dropped_domain
    stats.dropped_candidate_cap = dropped_cap
    stats.selected = len(selected)

    if config.debug:
        for candidate in selected:
            _log_keep(candidate)
        for reason, count in (
            ("domain_cap", dropped_domain),
            ("candidate_cap", dropped_cap),
        ):
            if count:
                logger.info("DROP reason=%s count=%s", reason, count)

    articles = [to_raw_article(candidate, known) for candidate in selected]
    logger.info(stats.summary_line())

    return DiscoveryOutcome(
        report=CollectResult(
            source_id=DISCOVERY_SOURCE_ID,
            source_name=DISCOVERY_SOURCE_NAME,
            success=True,
            fetched=stats.raw_results,
            valid=articles,
            discovery=True,
        ),
        stats=stats,
        candidates=selected,
        errors=errors,
    )


def _merge_by_url(candidates: Iterable[DiscoveryCandidate]) -> list[DiscoveryCandidate]:
    """One candidate per canonical URL, carrying every *distinct* query that found it.

    This is what makes RRF possible: a URL returned by three different topic
    queries becomes one candidate with three ranks rather than three candidates,
    and "several independent queries agree this is happening" becomes a signal.
    The first spelling of the URL wins for display, because a title and snippet
    are display concerns and the canonical form is what identity is judged on.

    One query contributes at most once. A provider that lists the same page twice
    in one answer has made a ranking mistake, not cast a second vote, and summing
    both copies would let that mistake outrank a page two queries genuinely agree
    on. The better of the two ranks is kept, because a rank is a position and the
    page did occupy the higher one.
    """
    merged: dict[str, DiscoveryCandidate] = {}
    best_ranks: dict[str, dict[str, int]] = {}
    for candidate in candidates:
        key = candidate.canonical_url or candidate.url
        existing = merged.get(key)
        if existing is None:
            merged[key] = candidate
            best_ranks[key] = dict(zip(candidate.matched_queries, candidate.query_ranks))
            continue
        ranks = best_ranks[key]
        for query, rank in zip(candidate.matched_queries, candidate.query_ranks):
            previous = ranks.get(query)
            ranks[query] = rank if previous is None else min(previous, rank)
        if not existing.title and candidate.title:
            existing.title = candidate.title
        if not existing.snippet and candidate.snippet:
            existing.snippet = candidate.snippet

    for key, candidate in merged.items():
        ranks = best_ranks[key]
        candidate.matched_queries = list(ranks)
        candidate.query_ranks = [ranks[query] for query in candidate.matched_queries]
    return list(merged.values())

def discovery_debug_enabled() -> bool:
    """Whether per-candidate KEEP/DROP logging is on."""
    from app.config.discovery import DEBUG_ENV

    return (os.getenv(DEBUG_ENV) or "").strip().lower() in {"1", "true", "yes", "on"}


def format_discovery_stats(stats: DiscoveryStats) -> str:
    """The refresh report block: the funnel, stage by stage."""
    return "\n".join(
        [
            "Web discovery (Tavily)",
            f"Queries: {stats.queries}",
            f"Successful queries: {stats.successful_queries}",
            f"Failed queries: {stats.failed_queries}",
            f"Raw results: {stats.raw_results}",
            f"Inside rolling 24h: {stats.inside_24h}",
            f"Dropped (no publish time): {stats.dropped_missing_time}",
            f"Dropped (outside 24h): {stats.dropped_outside_window}",
            f"Dropped (not AI): {stats.dropped_not_ai}",
            f"Dropped (social surface): {stats.dropped_social}",
            f"Unique URLs: {stats.unique_urls}",
            f"Matched several queries: {stats.matched_multiple_queries}",
            f"Dropped (domain cap): {stats.dropped_domain_cap}",
            f"Dropped (candidate cap): {stats.dropped_candidate_cap}",
            f"Selected: {stats.selected}",
        ]
    )


def format_discovery_candidates(candidates: Sequence[DiscoveryCandidate]) -> str:
    """The selected candidates, one block each, in the order they were ranked.

    This is the dry-run view: exactly what the refresh is about to hand to article
    extraction and the LLM, with the RRF score and hit count that put each one
    there. Printed only in debug mode, because a normal refresh logs one line and
    does not need 24 blocks of terminal output.
    """
    if not candidates:
        return "Web discovery candidates: none"
    lines = [f"Web discovery candidates: {len(candidates)}"]
    for index, candidate in enumerate(candidates, start=1):
        published = candidate.published_at.isoformat() if candidate.published_at else "unknown"
        lines.append(
            f"{index}. rrf={candidate.rrf_score:.6f} hits={candidate.hits} "
            f"domain={candidate.domain or '-'}"
        )
        lines.append(f"   title: {candidate.title or '(no title)'}")
        lines.append(f"   published_at: {published}")
        lines.append("   queries: " + ", ".join(candidate.matched_queries))
        lines.append(f"   url: {candidate.url}")
    return chr(10).join(lines)
