from app.services.digest_store import store


def main() -> None:
    reports = store.refresh()
    total_fetched = 0
    total_valid = 0
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
        total_fetched += report.fetched
        total_valid += len(report.valid)

    digest = store.get_today()
    stats = store.last_llm_stats
    print("Total:")
    print(f"Fetched: {total_fetched}")
    print(f"Valid: {total_valid}")
    print(f"Last 24h: {store.last_recent_count}")
    print(f"After dedup: {stats.candidates}")
    if failed:
        print(f"Failed: {', '.join(failed)}")
    else:
        print("Failed: none")
    print()
    print(f"Candidates: {stats.candidates}")
    print("LLM:")
    print(f"Enabled: {str(stats.enabled).lower()}")
    print(f"Success: {stats.success}")
    print(f"Cache hit: {stats.cache_hits}")
    print(f"Fallback: {stats.fallback}")
    print(f"Failed: {stats.failed}")
    if stats.input_tokens or stats.output_tokens:
        print(f"Input tokens: {stats.input_tokens}")
        print(f"Output tokens: {stats.output_tokens}")
    print()
    for item in digest.news[:12]:
        score = item.importance_score
        label = f"{score:02d}" if score is not None else "--"
        print(f"[{label}] {item.source} | {item.title_cn}")


if __name__ == "__main__":
    main()
