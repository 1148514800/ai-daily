from __future__ import annotations

import os
import sys

from app.services.digest_store import store
from app.services.github_store import GitHubRefreshStats, RepoDecision, github_store

DEBUG_ENV = "AI_DAILY_DEBUG_GITHUB"


def _configure_stdout() -> None:
    """Keep the debug command usable on non-UTF-8 Windows consoles."""
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass


def _debug_enabled() -> bool:
    return os.getenv(DEBUG_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


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
    reports = store.refresh()
    github_stats: GitHubRefreshStats = github_store.refresh()

    print("RSS")
    failed: list[str] = []
    for report in reports:
        print(f"{report.source_name}:")
        print(f"Fetched: {report.fetched}")
        print(f"Valid: {len(report.valid)}")
        print(f"Skipped: {report.skipped}")
        if report.error:
            print(f"Error: {report.error}")
            failed.append(report.source_name)
        print()

    article_stats = store.last_llm_stats
    print(f"Candidates: {article_stats.candidates}")
    print(f"After dedup: {article_stats.candidates}")
    if failed:
        print(f"Failed: {', '.join(failed)}")
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

    print("Final projects")
    for index, project in enumerate(github_store.list_projects(), start=1):
        rank = project.rank if project.rank is not None else "-"
        delta = project.stars_delta if project.stars_delta is not None else "-"
        print(f"#{index} (trending #{rank}) {project.repo}")
        print(f"  stars={project.stars} today={delta}")
        print(f"  {project.summary_cn}")
    print()

    print("GitHub API")
    remaining = github_stats.rate_limit_remaining
    print(f"Remaining: {remaining if remaining is not None else 'unknown'}")
    print()

    gh_llm = github_stats.llm_stats
    print("LLM")
    print(f"Article success: {article_stats.success}")
    print(f"GitHub success: {gh_llm.success}")
    print(f"Cache hit: {article_stats.cache_hits + gh_llm.cache_hits}")
    print(f"Fallback: {article_stats.fallback + gh_llm.fallback}")
    print()

    digest = store.get_today()
    for item in digest.news[:8]:
        score = item.importance_score
        label = f"{score:02d}" if score is not None else "--"
        print(f"[{label}] {item.source} | {item.title_cn}")


if __name__ == "__main__":
    main()
