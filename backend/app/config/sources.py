"""The AI news sources the daily collectors read.

Every source feeds the same pipeline (RawArticle -> window filter -> dedupe ->
LLM enrich -> NewsItem -> DailyDigest); the config only says where to read and
how the source should be ranked when two of them cover the same event.

``kind`` selects the collector: ``rss`` uses feedparser, ``html`` uses the
per-source extractor registered in ``app.collectors.html``. A source is only
listed here once its collection method has been verified to be stable and
public, so nothing depends on a private proxy or a login.

``source_type`` is one of ``official`` / ``research`` / ``media`` and is the
single place that decides a source's class. The API returns it and the client
only renders it, so the two can never disagree about whether Hugging Face is a
research lab or a news outlet. GitHub Trending is deliberately *not* a
NewsSource: it is a developer signal with its own collector and its own section.

X / Twitter is deliberately absent and must not be added: the platform has no
stable public read API for this use, and scraping it would need a browser.
"""

from __future__ import annotations

from dataclasses import dataclass

# Priority numbers only order sources within the same source_type; official
# sources always win over research, which always wins over media, whatever the
# priority. The three classes therefore occupy contiguous bands.
OFFICIAL_PRIORITY = 10
RESEARCH_PRIORITY = 60
MEDIA_PRIORITY = 120

# How a source is read. ``rss`` uses feedparser, ``html`` uses the matching
# extractor in app.collectors.html.
NEWS_SOURCE_KINDS = ("rss", "html")

# How a source is classified. ``official`` is a first-party model or product
# vendor, ``research`` a lab publishing research, ``media`` second-hand
# reporting. Nothing else is accepted: an unknown value would silently fall into
# the ranking's "unknown" bucket instead of failing where it was written.
NEWS_SOURCE_TYPES = ("official", "research", "media")


@dataclass(frozen=True)
class NewsSource:
    id: str
    name: str
    url: str
    source_type: str
    enabled: bool = True
    priority: int = 100
    kind: str = "rss"
    # True for a feed that carries the outlet's whole output rather than one AI
    # section. Those entries are filtered by AI evidence before they join the
    # pipeline, so a stray non-AI story never reaches dedupe or the LLM.
    requires_ai_filter: bool = False


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
        priority=12,
        kind="html",
    ),
    NewsSource(
        id="deepmind",
        name="Google DeepMind",
        url="https://deepmind.google/blog/rss.xml",
        source_type="official",
        priority=14,
    ),
    NewsSource(
        id="meta",
        name="Meta AI",
        url="https://engineering.fb.com/category/ai-research/feed/",
        source_type="official",
        priority=16,
    ),
    NewsSource(
        id="nvidia",
        name="NVIDIA",
        url="https://blogs.nvidia.com/feed/",
        source_type="official",
        priority=18,
    ),
    NewsSource(
        id="deepseek",
        name="DeepSeek",
        url="https://api-docs.deepseek.com/news/",
        source_type="official",
        priority=20,
        kind="html",
    ),
    NewsSource(
        id="qwen",
        name="Qwen",
        url="https://qwenlm.github.io/blog/index.xml",
        source_type="official",
        priority=22,
    ),
    NewsSource(
        id="kimi",
        name="Kimi",
        url="https://www.kimi.com/en/blog/",
        source_type="official",
        priority=24,
        kind="html",
    ),
    NewsSource(
        id="mistral",
        name="Mistral AI",
        url="https://mistral.ai/rss.xml",
        source_type="official",
        priority=26,
    ),
    NewsSource(
        id="cohere",
        name="Cohere",
        url="https://cohere.com/blog",
        source_type="official",
        priority=28,
        kind="html",
    ),
    NewsSource(
        id="cursor",
        name="Cursor",
        url="https://cursor.com/blog",
        source_type="official",
        priority=30,
        kind="html",
    ),
    # --- research labs ---
    NewsSource(
        id="huggingface",
        name="Hugging Face",
        url="https://huggingface.co/blog/feed.xml",
        source_type="research",
        priority=60,
    ),
    NewsSource(
        id="microsoft-research",
        name="Microsoft Research",
        url="https://www.microsoft.com/en-us/research/feed/",
        source_type="research",
        priority=70,
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
        id="ars-technica",
        name="Ars Technica",
        url="https://arstechnica.com/ai/feed/",
        source_type="media",
        priority=130,
        # The RSS feed carries the site's AI category, which still includes
        # gadget and business stories that only brush against AI (a robot dog
        # review, a data-centre bankruptcy). Those are dropped by an explicit AI
        # relevance check rather than by the substring "AI".
        requires_ai_filter=True,
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
