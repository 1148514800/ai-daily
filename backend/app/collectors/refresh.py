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
    print("Total:")
    print(f"Fetched: {total_fetched}")
    print(f"Valid: {total_valid}")
    print(f"Last 24h: {store.last_recent_count}")
    print(f"After dedup: {len(digest.news)}")
    if failed:
        print(f"Failed: {', '.join(failed)}")
    else:
        print("Failed: none")
    print()
    for item in digest.news[:12]:
        print(f"{item.published_at} | {item.source} | {item.title_original}")


if __name__ == "__main__":
    main()
