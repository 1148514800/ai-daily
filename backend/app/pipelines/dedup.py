import re
from datetime import datetime, timedelta, timezone

from app.collectors.raw import RawArticle
from app.config.sources import RSSSource, source_map

PUNCTUATION_RE = re.compile(r"[.,;:!?\"'`()\[\]{}]+")
WHITESPACE_RE = re.compile(r"\s+")


def normalize_title(title: str) -> str:
    value = title.strip().lower()
    value = PUNCTUATION_RE.sub(" ", value)
    value = WHITESPACE_RE.sub(" ", value).strip()
    return value


def _as_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def within_hours(left: datetime | None, right: datetime | None, hours: int) -> bool:
    start = _as_aware(left)
    end = _as_aware(right)
    if start is None or end is None:
        return False
    return abs(start - end) <= timedelta(hours=hours)


def choose_winner(articles: list[RawArticle], sources: dict[str, RSSSource] | None = None) -> RawArticle:
    lookup = sources or source_map()

    def sort_key(article: RawArticle) -> tuple:
        source = lookup.get(article.source_id)
        official = 0 if article.source_type == "official" else 1
        priority = source.priority if source is not None else 1000
        published = _as_aware(article.published_at) or datetime.max.replace(tzinfo=timezone.utc)
        return (official, priority, published, article.canonical_url, article.url)

    return sorted(articles, key=sort_key)[0]


def dedupe_articles(articles: list[RawArticle], sources: dict[str, RSSSource] | None = None) -> list[RawArticle]:
    lookup = sources or source_map()
    by_url: dict[str, list[RawArticle]] = {}
    for article in articles:
        key = article.canonical_url or article.url
        by_url.setdefault(key, []).append(article)

    after_url = [choose_winner(group, lookup) for group in by_url.values()]

    clusters: list[list[RawArticle]] = []
    for article in sorted(after_url, key=lambda item: (normalize_title(item.title), item.canonical_url, item.url)):
        title_key = normalize_title(article.title)
        placed = False
        if title_key:
            for cluster in clusters:
                if any(
                    normalize_title(other.title) == title_key
                    and within_hours(article.published_at, other.published_at, 48)
                    for other in cluster
                ):
                    cluster.append(article)
                    placed = True
                    break
        if not placed:
            clusters.append([article])

    winners = [choose_winner(cluster, lookup) for cluster in clusters]
    winners.sort(
        key=lambda item: (
            _as_aware(item.published_at) or datetime.min.replace(tzinfo=timezone.utc),
            item.canonical_url,
        ),
        reverse=True,
    )
    return winners
