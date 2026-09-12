from app.services.digest_store import store
from app.services.github_store import github_store


def main() -> None:
    reports = store.refresh()
    github_stats = github_store.refresh()
    total_fetched = 0
    total_valid = 0
    failed: list[str] = []

    print("RSS")
    for report in reports:
        print(f"{report.source_name}:")
        print(f"Fetched: {report.fetched}")
        print(f"Valid: {len(report.valid)}")
        print(f"Skipped: {report.skipped}")
        if report.error:
            print(f"Error: {report.error}")
            failed.append(report.source_name)
        print()
        total_fetched += report.fetched
        total_valid += len(report.valid)

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
    print()
    for project in github_store.list_projects()[:8]:
        rank = project.rank if project.rank is not None else "-"
        delta = project.stars_delta if project.stars_delta is not None else "-"
        print(f"#{rank} {project.repo} stars={project.stars} today={delta} | {project.summary_cn}")


if __name__ == "__main__":
    main()
