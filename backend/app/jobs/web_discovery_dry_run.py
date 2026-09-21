"""See what Web Discovery would hand the pipeline, without running the pipeline.

    cd backend
    uv run python -m app.jobs.web_discovery_dry_run

Phase 10.15 asks for one thing before the layer is switched on for real: look at
the 24 candidates it produces and judge them by hand. The refresh debug output
almost does that, but a refresh is not read-only - it extracts pages, calls the
LLM, and writes a digest. This job is the safe half of that: it runs *only* the
discovery pass and prints the funnel and the final list, and it never opens the
database, never fetches an article body, never calls the LLM and never persists
anything. Running it changes nothing on the machine except the provider bill.

The funnel it prints is the production one, produced by the production module
with the production queries, so the numbers are directly comparable with a real
refresh rather than with a reimplementation of it.

This is a diagnostic, not a second entry point into the pipeline. Nothing calls
it, and switching ``WEB_DISCOVERY_ENABLED`` off leaves it inert like everything
else in the layer.

Exit status: 0 discovery ran and returned candidates, 1 discovery ran and found
nothing usable (the configuration works, the recall does not), 2 the job could
not run at all because the layer is off or has no key.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import datetime, timezone

from app.config.discovery import (
    DEFAULT_MAX_CANDIDATES,
    DEFAULT_MAX_PER_DOMAIN,
    DEFAULT_RESULTS_PER_QUERY,
    load_web_discovery_settings,
)
from app.config.env import load_dotenv
from app.services.digest_window import as_utc
from app.services.web_discovery import (
    DiscoveryCandidate,
    collect_web_discovery,
    format_discovery_stats,
)

NO_CANDIDATES_EXIT = 1
NOT_RUNNABLE_EXIT = 2


def format_candidate_table(candidates: list[DiscoveryCandidate]) -> str:
    """The final list, one numbered block each, best-ranked first."""
    if not candidates:
        return "Selected candidates: none"
    lines = [f"Selected candidates: {len(candidates)}", ""]
    for index, candidate in enumerate(candidates, start=1):
        published = candidate.published_at.isoformat() if candidate.published_at else "unknown"
        lines.append(f"{index}. {candidate.title or '(no title)'}")
        lines.append(f"   domain: {candidate.domain or '-'}")
        lines.append(f"   published_at: {published}")
        lines.append(f"   rrf_score: {candidate.rrf_score:.6f}   hits: {candidate.hits}")
        lines.append(f"   provider_score: {candidate.provider_score or '-'}")
        lines.append(f"   queries: " + ", ".join(candidate.matched_queries))
        lines.append(f"   url: {candidate.url}")
        lines.append("")
    return "\n".join(lines).rstrip()


def format_domain_distribution(candidates: list[DiscoveryCandidate]) -> str:
    """How the allowance was actually spent, which is the diversity question."""
    counts = Counter(candidate.domain or "-" for candidate in candidates)
    if not counts:
        return "Domain distribution: none"
    width = max(len(domain) for domain in counts)
    lines = [f"Domain distribution: {len(counts)} domains in {sum(counts.values())} candidates"]
    for domain, count in counts.most_common():
        lines.append(f"  {domain.ljust(width)}  {count}")
    return "\n".join(lines)


def format_source_classes(candidates: list[DiscoveryCandidate]) -> str:
    """Which known source each candidate maps to, and which are new.

    Read straight from the same mapping the pipeline uses, so a candidate that
    says ``official`` here will reach the ranking as ``official`` and a
    ``web:<domain>`` one will reach it as ``media``.
    """
    from app.services.web_discovery import to_raw_article

    known: list[str] = []
    discovered: list[str] = []
    for candidate in candidates:
        article = to_raw_article(candidate)
        if article.source_id.startswith("web:"):
            discovered.append(f"{candidate.domain} ({article.source_type})")
        else:
            known.append(f"{candidate.domain} -> {article.source_id} ({article.source_type})")
    return "\n".join(
        [
            f"Known configured sources: {len(known)}",
            *(f"  {line}" for line in known),
            f"New / discovered: {len(discovered)}",
            *(f"  {line}" for line in discovered),
        ]
    )


def run(now: datetime | None = None, *, settings=None) -> int:
    """Run the discovery pass once and print it. Never raises."""
    config = settings or load_web_discovery_settings()
    print("Web Discovery dry run (read-only)")
    print(f"Provider: {config.provider}")
    print("Endpoint: https://api.tavily.com/search")
    print(f"Results per query: {config.results_per_query}")
    print(f"Max candidates: {config.max_candidates}")
    print(f"Max per domain: {config.max_per_domain}")
    print(f"Timeout: {config.timeout:g}s")
    print()

    if not config.enabled:
        print("WEB_DISCOVERY_ENABLED is false, so the layer is switched off.")
        print("Enable it in backend/.env to run this diagnostic.")
        return NOT_RUNNABLE_EXIT
    if not config.api_key:
        print("Missing environment variable: TAVILY_API_KEY")
        print("Set it in backend/.env (copy backend/.env.example) or in the environment.")
        return NOT_RUNNABLE_EXIT

    current = as_utc(now or datetime.now(timezone.utc))
    print(f"Reference time: {current.isoformat()}")
    outcome = collect_web_discovery(current, settings=config)
    if outcome is None:
        print("The layer reported itself as not runnable.")
        return NOT_RUNNABLE_EXIT

    print()
    print(format_discovery_stats(outcome.stats))

    if outcome.errors:
        print()
        print(f"Failed queries: {len(outcome.errors)}")
        for error in outcome.errors:
            print(f"  {error}")

    print()
    print("Selected candidates (what would enter article extraction and the LLM)")
    print()
    print(format_candidate_table(outcome.candidates))
    print()
    print(format_domain_distribution(outcome.candidates))
    print()
    print(format_source_classes(outcome.candidates))
    print()

    if outcome.candidates:
        print("VERDICT: candidates found. Inspect them above before enabling the layer.")
        return 0
    print("VERDICT: no candidate survived the funnel.")
    if outcome.errors:
        print("Every query failed; the provider or the key is unusable.")
    else:
        print("Queries answered but nothing was recent, AI-related and non-duplicate.")
    return NO_CANDIDATES_EXIT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print what Web Discovery would hand the pipeline, without running it"
    )
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=None,
        help=f"override the candidate cap (default: {DEFAULT_MAX_CANDIDATES})",
    )
    parser.add_argument(
        "--max-per-domain",
        type=int,
        default=None,
        help=f"override the per-domain cap (default: {DEFAULT_MAX_PER_DOMAIN})",
    )
    parser.add_argument(
        "--results-per-query",
        type=int,
        default=None,
        help=f"override results per query (default: {DEFAULT_RESULTS_PER_QUERY})",
    )
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    load_dotenv()
    settings = load_web_discovery_settings()
    if args.max_candidates is not None or args.max_per_domain is not None or args.results_per_query is not None:
        from dataclasses import replace

        settings = replace(
            settings,
            max_candidates=args.max_candidates or settings.max_candidates,
            max_per_domain=args.max_per_domain or settings.max_per_domain,
            results_per_query=args.results_per_query or settings.results_per_query,
        )
    return run(settings=settings)


if __name__ == "__main__":
    raise SystemExit(main())