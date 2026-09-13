"""The AI news sources the daily collectors read.

Every source feeds the same pipeline (RawArticle -> window filter -> dedupe ->
LLM enrich -> NewsItem -> DailyDigest); the config only says where to read and
how the source should be ranked when two of them cover the same event.

``kind`` selects the collector: ``rss`` uses feedparser, ``html`` uses the
per-source extractor registered in ``app.collectors.html``. A source is only
listed here once its collection method has been verified to be stable and
public, so nothing depends on a private proxy or a login.
"""

from __future__ import annotations

from dataclasses import dataclass

# Priority numbers only order sources within the same source_type; official
# sources always win over media in dedupe, whatever their priority.
OFFICIAL_PRIORITY = 10

# How a source is read. ``rss`` uses feedparser, ``html`` uses the matching
# extractor in app.collectors.html.
NEWS_SOURCE_KINDS = ("rss", "html")


@dataclass(frozen=True)
class NewsSource:
    id: str
    name: str
    url: str
    source_type: str
    enabled: bool = True
    priority: int = 100
    kind: str = "rss"


SOURCES: tuple[NewsSource, ...] = (
    # --- official, first-party ---
    NewsSource(
        id="openai",
        name="OpenAI",
        url="https://openai.com/news/rss.xml",
        source_type="official",
        priority=10,
    ),
    NewsSource(
        id="anthropic",
        name="Anthropic",
        url="https://www.anthropic.com/news",
        source_type="official",
        priority=20,
        kind="html",
    ),
    NewsSource(
        id="deepmind",
        name="Google DeepMind",
        url="https://deepmind.google/blog/rss.xml",
        source_type="official",
        priority=30,
    ),
    NewsSource(
        id="meta",
        name="Meta AI",
        url="https://engineering.fb.com/category/ai-research/feed/",
        source_type="official",
        priority=40,
    ),
    NewsSource(
        id="nvidia",
        name="NVIDIA",
        url="https://blogs.nvidia.com/feed/",
        source_type="official",
        priority=50,
    ),
    NewsSource(
        id="deepseek",
        name="DeepSeek",
        url="https://api-docs.deepseek.com/news/",
        source_type="official",
        priority=60,
        kind="html",
    ),
    NewsSource(
        id="qwen",
        name="Qwen",
        url="https://qwenlm.github.io/blog/index.xml",
        source_type="official",
        priority=70,
    ),
    NewsSource(
        id="kimi",
        name="Kimi",
        url="https://www.kimi.com/en/blog/",
        source_type="official",
        priority=80,
        kind="html",
    ),
    # --- community blog ---
    NewsSource(
        id="huggingface",
        name="Hugging Face",
        url="https://huggingface.co/blog/feed.xml",
        source_type="blog",
        priority=90,
    ),
    # --- media, second-hand reporting ---
    NewsSource(
        id="techcrunch-ai",
        name="TechCrunch AI",
        url="https://techcrunch.com/category/artificial-intelligence/feed/",
        source_type="media",
        priority=120,
    ),
    NewsSource(
        id="qbitai",
        name="量子位",
        url="https://www.qbitai.com/feed",
        source_type="media",
        priority=130,
    ),
)


def all_sources() -> tuple[NewsSource, ...]:
    return SOURCES


def enabled_sources() -> tuple[NewsSource, ...]:
    return tuple(source for source in SOURCES if source.enabled)


def source_by_id(source_id: str) -> NewsSource:
    for source in SOURCES:
        if source.id == source_id:
            return source
    raise KeyError(source_id)


def source_map() -> dict[str, NewsSource]:
    return {source.id: source for source in SOURCES}
