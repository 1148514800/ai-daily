from __future__ import annotations

import os
import sys

from app.db.session import init_db
from app.jobs.daily_refresh import run_manual_refresh
from app.services.digest_store import store
from app.services.event_dedup import format_event_dedup
from app.services.article_extractor import format_extraction_stats
from app.services.media_selection import (
    format_media_selection,
    media_debug_enabled,
)
from app.services.news_ranker import format_ranking, ranking_debug_enabled
from app.services.github_store import GitHubRefreshStats, RepoDecision, github_store
from app.services.source_health import build_report, format_source_health

DEBUG_ENV = "AI_DAILY_DEBUG_GITHUB"
EXTRACTION_DEBUG_ENV = "AI_DAILY_DEBUG_EXTRACTION"


def _configure_stdout() -> None:
    """Keep the debug command usable on non-UTF-8 Windows consoles."""
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass


def _debug_enabled() -> bool:
    return os.getenv(DEBUG_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _extraction_debug_enabled() -> bool:
    return os.getenv(EXTRACTION_DEBUG_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _media_debug_enabled() -> bool:
    return media_debug_enabled()


def _format_list(items: list[str]) -> str:
    return "[" + ", ".join(items) + "]" if items else "[]"


def _format_fields(fields: list[str]) -> str:
    return "/".join(fields) if fields else "-"


def _print_decision(item: RepoDecision, *, debug: bool) -> None:
    print("ACCEPT" if item.accepted else "REJECT")
    print(f"#{item.rank} {item.repo}")
    print(f"score={item.score}")
    print(f"strong={_format_list(item.strong)}")
    print(f"weak={_format_list(item.weak)}")
    print(f"source={_format_fields(item.matched_fields)}")
    if debug:
        print(f"mode={item.mode}")
        print(f"route={item.route}")
        print(f"metadata={'yes' if item.metadata_available else 'no'}")
        if item.negative:
            print(f"negative={_format_list(item.negative)}")
    if not item.accepted:
        print(f"reason={item.reason}")
    print()


def print_github_filtering(decisions: list[RepoDecision], *, debug: bool = False) -> None:
    """Print the GitHub AI filtering result. Reused by tests."""
    if not decisions:
        return
    accepted = [item for item in decisions if item.accepted]
    rejected = [item for item in decisions if not item.accepted]

    print("AI filtering:")
    print()
    for item in accepted:
        _print_decision(item, debug=debug)

    if debug:
        for item in rejected:
            _print_decision(item, debug=True)
    else:
        print(f"({len(rejected)} rejected; set {DEBUG_ENV}=1 for per-repo reasons)")
        print()

    print(f"Accepted: {len(accepted)}/{len(decisions)}")
    print()


def main() -> None:
    _configure_stdout()
    debug = _debug_enabled()
    init_db()
    outcome = run_manual_refresh()
    combined = outcome.combined
    if combined is None:
        print("Refresh did not complete")
        print(f"Status: {outcome.status}")
        if outcome.error:
            print(f"Error: {outcome.error}")
        return
    print(f"Trigger: {outcome.trigger}")
    print(f"Status: {outcome.status}")
    print()
    reports = combined.reports
    github_stats: GitHubRefreshStats = combined.github_stats
    article_stats = store.last_llm_stats
    health = build_report(reports)

    print(format_source_health(health))
    for report in reports:
        if report.error:
            print(f"Error ({report.source_name}): {report.error}")

    # The funnel: collected -> inside the issue window -> one row per URL.
    print(f"Fetched: {store.last_fetched_count}")
    print(f"In window: {store.last_recent_count}")
    print(f"After dedup: {store.last_deduped_count}")
    print(f"Candidates: {article_stats.candidates}")
    print()

    print(format_extraction_stats(store.last_extraction_stats, debug=_extraction_debug_enabled()))
    print()

    event_stats = store.last_event_stats
    print("Event dedup:")
    print(f"Candidates: {event_stats.candidates}")
    print(f"Clusters: {event_stats.clusters}")
    print(f"Duplicates merged: {event_stats.merged}")
    if debug:
        for decision in event_stats.decisions:
            print()
            for line in format_event_dedup(decision).splitlines():
                print(line)
    print()

    print(format_media_selection(store.last_media_stats, debug=_media_debug_enabled() or debug))
    print()

    print("Source classes (after event dedup)")
    counts = store.last_type_counts
    for name in ("official", "research", "media"):
        print(f"{name.capitalize()}: {counts.get(name, 0)}")
    print()

    print(format_ranking(store.last_ranking_stats, debug=ranking_debug_enabled() or debug))
    print()

    print("GitHub Trending")
    print(f"Fetched: {github_stats.fetched}")
    print(f"Parsed: {github_stats.parsed}")
    print(f"AI candidates: {github_stats.ai_candidates}")
    print(f"Metadata success: {github_stats.metadata_success}")
    print(f"Selected: {github_stats.selected}")
    if github_stats.used_previous:
        print("Used previous snapshot: true")
    if github_stats.error:
        print(f"Error: {github_stats.error}")
    print()

    print_github_filtering(github_stats.decisions, debug=debug)

    if combined.saved:
        print(f"Digest saved: {combined.date}")
        print(f"News: {store.last_news_count}")
        print(f"GitHub: {store.last_github_count}")
    else:
        print(f"Kept existing digest: {combined.date}")
    print()

    digests, news_total, github_total = store.stats()
    print("Database")
    print(f"Daily digests: {digests}")
    print(f"News total: {news_total}")
    print(f"GitHub repos total: {github_total}")
    print()

    digest = store.get_digest(combined.date)
    ranking = {entry.news_id: entry for entry in store.last_ranking_stats.ranked}
    print("Daily Ranking")
    print()
    for item in digest.news:
        entry = ranking.get(item.id)
        score = f"{entry.rank_score:5.1f}" if entry else "  -- "
        importance = item.importance_score
        importance_label = f"{importance:02d}" if importance is not None else "--"
        topic = entry.topic if entry else "-"
        company = (entry.company or "-") if entry else "-"
        print(f"{item.rank}. [{score}] {item.source} | {item.title_cn}")
        print(
            f"     source={item.source} topic={topic} company={company} "
            f"importance={importance_label}"
        )
    print()
    for index, project in enumerate(digest.github_projects, start=1):
        delta = project.stars_delta if project.stars_delta is not None else "-"
        print(f"#{index} {project.repo} stars={project.stars} today={delta} | {project.summary_cn}")


if __name__ == "__main__":
    main()
