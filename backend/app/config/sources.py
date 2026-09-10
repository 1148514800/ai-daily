from dataclasses import dataclass


@dataclass(frozen=True)
class RSSSource:
    id: str
    name: str
    url: str
    source_type: str
    enabled: bool = True
    priority: int = 100


RSS_SOURCES: tuple[RSSSource, ...] = (
    RSSSource(
        id="openai",
        name="OpenAI",
        url="https://openai.com/news/rss.xml",
        source_type="official",
        priority=10,
    ),
    RSSSource(
        id="deepmind",
        name="Google DeepMind",
        url="https://deepmind.google/blog/rss.xml",
        source_type="official",
        priority=20,
    ),
    RSSSource(
        id="huggingface",
        name="Hugging Face",
        url="https://huggingface.co/blog/feed.xml",
        source_type="blog",
        priority=30,
    ),
)


def enabled_sources() -> tuple[RSSSource, ...]:
    return tuple(source for source in RSS_SOURCES if source.enabled)


def source_by_id(source_id: str) -> RSSSource:
    for source in RSS_SOURCES:
        if source.id == source_id:
            return source
    raise KeyError(source_id)


def source_map() -> dict[str, RSSSource]:
    return {source.id: source for source in RSS_SOURCES}
