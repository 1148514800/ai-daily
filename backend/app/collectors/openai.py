from dataclasses import replace

from app.collectors.rss import CollectResult, collect_source, parse_feed, within_last_hours
from app.config.sources import source_by_id

OPENAI_RSS_URL = "https://openai.com/news/rss.xml"
DEFAULT_TIMEOUT = 10.0


def parse_openai_feed(xml: str) -> CollectResult:
    return parse_feed(xml, source_by_id("openai"))


def collect_openai_news(*, url: str = OPENAI_RSS_URL, timeout: float = DEFAULT_TIMEOUT, fetch_text=None) -> CollectResult:
    source = source_by_id("openai")
    if url != source.url:
        source = replace(source, url=url)
    return collect_source(source, timeout=timeout, fetch_text=fetch_text)


def main() -> None:
    from datetime import datetime, timedelta, timezone

    result = collect_openai_news()
    now = datetime.now(timezone.utc)
    recent = [
        item
        for item in result.news_items
        if item.published_at
        and now - datetime.fromisoformat(item.published_at) <= timedelta(hours=24)
    ]
    print("OpenAI:")
    print(f"Fetched: {result.fetched}")
    print(f"Valid: {len(result.valid)}")
    print(f"Skipped: {result.skipped}")
    if result.error:
        print(f"Error: {result.error}")
    print(f"Last 24h: {len(recent)}")
    print()
    preview = sorted(result.news_items, key=lambda item: item.published_at, reverse=True)[:8]
    for item in preview:
        print(f"{item.published_at} | {item.title_original}")


if __name__ == "__main__":
    main()
