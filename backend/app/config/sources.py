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

# Which first-party surface a source reads. One company usually publishes on
# several of them, so a company is not one source: Anthropic's newsroom, its
# research index and its engineering blog are three channels of the same
# organization, and a story on any of them is still an Anthropic announcement.
#
# ``channel`` is deliberately separate from ``source_type``. ``source_type``
# says how trustworthy the origin is (a first-party vendor beats a lab beats a
# news outlet); ``channel`` says which official surface it came from. Anthropic
# Institute is therefore ``source_type="official"``, ``channel="research"``: it
# is still Anthropic speaking, whatever kind of page it is printed on.
NEWS_CHANNELS = (
    "news",
    "research",
    "product",
    "engineering",
    "developer",
    "model",
    "security",
    "changelog",
    "cloud",
)


@dataclass(frozen=True)
class NewsSource:
    id: str
    name: str
    url: str
    source_type: str
    enabled: bool = True
    priority: int = 100
    kind: str = "rss"
    # The company that publishes this source, and which of its official
    # surfaces this is. Two sources of one company share ``organization`` but
    # never share ``channel``: that is what lets the health report show a
    # company's coverage instead of a flat list of feeds, and what tells a
    # future diversity pass that two entries come from the same vendor.
    organization: str = ""
    channel: str = "news"
    # True for a feed that carries the outlet's whole output rather than one AI
    # section. Those entries are filtered by AI evidence before they join the
    # pipeline, so a stray non-AI story never reaches dedupe or the LLM.
    requires_ai_filter: bool = False
    # Origin used to resolve a feed whose links are site-relative. Most feeds
    # publish absolute URLs and leave this empty; a Hugo blog that links
    # ``/blog/posts/x`` needs it, or every entry would be skipped for having no
    # usable URL. It is a resolution base, not a second address: nothing is ever
    # fetched from it.
    base_url: str = ""


SOURCES: tuple[NewsSource, ...] = (
    # --- official, first-party ---
    NewsSource(
        id="openai",
        organization="openai",
        channel="news",
        name="OpenAI",
        url="https://openai.com/news/rss.xml",
        source_type="official",
        priority=10,
    ),
    NewsSource(
        id="anthropic",
        organization="anthropic",
        channel="news",
        name="Anthropic",
        # One page, several channels: Anthropic's newsroom lists both /news/
        # posts and the institute essays that used to be missed, so the
        # extractor accepts every article path this page actually links to
        # rather than only /news/. Nothing is fetched twice for that.
        url="https://www.anthropic.com/news",
        source_type="official",
        priority=12,
        kind="html",
    ),
    NewsSource(
        id="anthropic-research",
        organization="anthropic",
        channel="research",
        name="Anthropic Research",
        url="https://www.anthropic.com/research",
        source_type="official",
        priority=42,
        kind="html",
    ),
    NewsSource(
        id="anthropic-engineering",
        organization="anthropic",
        channel="engineering",
        name="Anthropic Engineering",
        url="https://www.anthropic.com/engineering",
        source_type="official",
        priority=44,
        kind="html",
    ),
    NewsSource(
        id="deepmind",
        organization="google",
        channel="research",
        name="Google DeepMind",
        url="https://deepmind.google/blog/rss.xml",
        source_type="official",
        priority=14,
    ),
    NewsSource(
        id="meta",
        organization="meta",
        channel="research",
        name="Meta AI",
        url="https://engineering.fb.com/category/ai-research/feed/",
        source_type="official",
        priority=16,
    ),
    NewsSource(
        id="nvidia",
        organization="nvidia",
        channel="news",
        name="NVIDIA",
        url="https://blogs.nvidia.com/feed/",
        source_type="official",
        priority=18,
        # The corporate feed mixes AI work with GeForce NOW game launches and
        # hardware promotions. Those belong in a gaming roundup, not an AI
        # digest, so the feed is filtered by AI evidence before collection.
        requires_ai_filter=True,
    ),
    NewsSource(
        id="deepseek",
        organization="deepseek",
        channel="news",
        name="DeepSeek",
        url="https://api-docs.deepseek.com/news/",
        source_type="official",
        priority=20,
        kind="html",
    ),
    NewsSource(
        id="qwen",
        organization="alibaba",
        channel="model",
        name="Qwen",
        url="https://qwenlm.github.io/blog/index.xml",
        source_type="official",
        priority=22,
    ),
    NewsSource(
        id="kimi",
        organization="moonshot",
        channel="news",
        name="Kimi",
        url="https://www.kimi.com/en/blog/",
        source_type="official",
        priority=24,
        kind="html",
    ),
    NewsSource(
        id="mistral",
        organization="mistral",
        channel="news",
        name="Mistral AI",
        url="https://mistral.ai/rss.xml",
        source_type="official",
        priority=26,
    ),
    NewsSource(
        id="cohere",
        organization="cohere",
        channel="news",
        name="Cohere",
        url="https://cohere.com/blog",
        source_type="official",
        priority=28,
        kind="html",
    ),
    NewsSource(
        id="cursor",
        organization="cursor",
        channel="news",
        name="Cursor",
        url="https://cursor.com/blog",
        source_type="official",
        priority=30,
        kind="html",
    ),
    # --- official, first-party, Chinese vendors (Phase 10.13) ---
    #
    # The five below are the domestic model vendors. None of them publishes a
    # usable feed, so each is read from the one official surface that carries
    # dates and is stable: two embed their listing in the page as JSON, one
    # exposes a public JSON API, one is a plain server-rendered listing, and one
    # is a Hugo blog with a real RSS feed.
    NewsSource(
        id="bytedance-seed",
        organization="bytedance",
        channel="model",
        name="ByteDance Seed / 豆包",
        url="https://seed.bytedance.com/zh/blog",
        source_type="official",
        priority=32,
        kind="html",
    ),
    NewsSource(
        id="tencent-hunyuan",
        organization="tencent",
        channel="model",
        name="腾讯混元",
        # The public JSON listing the official blog itself reads. Preferred over
        # scraping hunyuan.tencent.com/news/blog, which is a client-rendered
        # shell with no article markup in the response at all.
        url="https://api.hunyuan.tencent.com/api/blog/publicList",
        source_type="official",
        priority=34,
        kind="html",
    ),
    NewsSource(
        id="baidu-ernie",
        organization="baidu",
        channel="model",
        name="百度文心",
        # Hugo's built-in feed. Its <link> values are site-relative, so the
        # origin has to be supplied for the feed to yield usable URLs.
        url="https://ernie.baidu.com/index.xml",
        source_type="official",
        priority=36,
        base_url="https://ernie.baidu.com",
    ),
    NewsSource(
        id="zhipu-glm",
        organization="zhipu",
        channel="news",
        name="智谱 GLM",
        url="https://www.zhipuai.cn/zh/news",
        source_type="official",
        priority=38,
        kind="html",
    ),
    NewsSource(
        id="minimax",
        organization="minimax",
        channel="news",
        name="MiniMax",
        # The canonical host; minimaxi.com redirects here.
        url="https://www.minimax.cn/blog",
        source_type="official",
        priority=40,
        kind="html",
    ),
    # --- official, additional channels of the same companies ---
    #
    # A company is not one source. The entries below are further first-party
    # surfaces of vendors already listed above, and they exist because the one
    # feed a company happened to publish was not where its news actually
    # appeared: an Anthropic essay on /institute/ is not on /news/, and Tencent
    # WorkBuddy is a Tencent Cloud product, not a Hunyuan model post.
    #
    # Every one of them is still ``source_type="official"``: it is the vendor
    # publishing about itself. Only the ``channel`` differs, which is what makes
    # "one event, one entry" work across a company's own surfaces.
    NewsSource(
        id="cursor-changelog",
        organization="cursor",
        channel="changelog",
        name="Cursor Changelog",
        # Features often ship here and nowhere else, so a blog-only source
        # would miss them entirely.
        url="https://cursor.com/changelog",
        source_type="official",
        priority=43,
        kind="html",
    ),
    NewsSource(
        id="cohere-research",
        organization="cohere",
        channel="research",
        name="Cohere Research",
        url="https://cohere.com/research",
        source_type="official",
        priority=45,
        kind="html",
    ),
    NewsSource(
        id="nvidia-developer",
        organization="nvidia",
        channel="developer",
        name="NVIDIA Developer",
        # The developer blog is where the CUDA, inference and framework work is
        # written up; the corporate feed carries much of the product marketing.
        # It is left unfiltered on purpose: this channel has no game promotions
        # to exclude, and the AI filter would drop real posts ("Dense vs. MoE
        # Models", "BioNeMo Inference Runtime") whose titles use no keyword the
        # filter recognises. Filtering costs recall here and buys nothing.
        url="https://developer.nvidia.com/blog/feed/",
        source_type="official",
        priority=47,
    ),
    NewsSource(
        id="meta-ai-blog",
        organization="meta",
        channel="research",
        name="Meta AI Blog",
        # No feed on this host, and the markup is hashed CSS-module classes, so
        # it is read by structure instead: a date element plus the article link
        # it belongs to.
        url="https://ai.meta.com/blog/",
        source_type="official",
        priority=49,
        kind="html",
    ),
    NewsSource(
        id="alibaba-model-studio",
        organization="alibaba",
        channel="model",
        name="阿里云百炼模型广场",
        # The dated catalogue of models the platform newly offers. Rows carry a
        # model id rather than a link of their own, so the model id is what
        # identifies a row.
        url="https://help.aliyun.com/zh/model-studio/newly-released-models",
        source_type="official",
        priority=51,
        kind="html",
    ),
    NewsSource(
        id="google-ai",
        organization="google",
        channel="product",
        name="Google AI Blog",
        url="https://blog.google/innovation-and-ai/technology/ai/rss/",
        source_type="official",
        priority=46,
    ),
    NewsSource(
        id="google-gemini",
        organization="google",
        channel="product",
        name="Google Gemini Blog",
        # A separate feed from the AI blog above, with little overlap: Gemini
        # product updates are published here and not there.
        url="https://blog.google/products-and-platforms/products/gemini/rss/",
        source_type="official",
        priority=48,
    ),
    NewsSource(
        id="google-research",
        organization="google",
        channel="research",
        name="Google Research",
        url="https://research.google/blog/rss/",
        source_type="official",
        priority=50,
    ),
    NewsSource(
        id="google-cloud-ai",
        organization="google",
        channel="cloud",
        name="Google Cloud AI",
        # The ``cloudblog.withgoogle.com`` host, not ``cloud.google.com``: the
        # latter answers with a JavaScript shell instead of a feed.
        url="https://cloudblog.withgoogle.com/products/ai-machine-learning/rss/",
        source_type="official",
        priority=52,
        requires_ai_filter=True,
    ),
    NewsSource(
        id="tencent-cloud-ai",
        organization="tencent",
        channel="cloud",
        name="腾讯云公告",
        # Tencent Cloud's own announcement list. It is a wide operations feed
        # (load balancers, databases, billing), so AI relevance is required
        # before an entry can join the digest.
        url="https://cloud.tencent.com/announce",
        source_type="official",
        priority=54,
        kind="html",
        requires_ai_filter=True,
    ),
    NewsSource(
        id="tencent-workbuddy",
        organization="tencent",
        channel="product",
        name="腾讯 WorkBuddy",
        # WorkBuddy is a Tencent Cloud AI product with its own release history;
        # its changelog is the only dated official surface it publishes.
        url="https://www.codebuddy.cn/docs/workbuddy/Changelog",
        source_type="official",
        priority=56,
        kind="html",
    ),
    # 火山引擎 (ByteDance's cloud) is deliberately absent. Its news list does
    # ship a machine-readable payload, but the listing has not been updated
    # since 2025-10-15, so a channel reading it would be empty every day: the
    # page is abandoned, not quiet. Doubao's product news is covered by the Seed
    # blog above. Recorded here so the gap is a decision rather than an
    # oversight.
    # --- research labs ---
    NewsSource(
        id="huggingface",
        organization="huggingface",
        channel="research",
        name="Hugging Face",
        url="https://huggingface.co/blog/feed.xml",
        source_type="research",
        priority=60,
    ),
    NewsSource(
        id="microsoft-research",
        organization="microsoft",
        channel="research",
        name="Microsoft Research",
        url="https://www.microsoft.com/en-us/research/feed/",
        source_type="research",
        priority=70,
    ),
    # --- media, second-hand reporting ---
    NewsSource(
        id="techcrunch-ai",
        organization="techcrunch",
        channel="news",
        name="TechCrunch AI",
        url="https://techcrunch.com/category/artificial-intelligence/feed/",
        source_type="media",
        priority=120,
    ),
    NewsSource(
        id="ars-technica",
        organization="ars-technica",
        channel="news",
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


# Official channels that were audited and found to have no stable public
# surface, recorded so the coverage report can say "unsupported" rather than
# leaving a company looking fully covered because nothing failed. Each entry is
# (organization, channel, why).
UNSUPPORTED_CHANNELS: tuple[tuple[str, str, str], ...] = (
    (
        "openai",
        "developer",
        "the API changelog publishes no feed and dates entries inconsistently",
    ),
    (
        "bytedance",
        "cloud",
        "火山引擎's news list has not been updated since 2025-10-15",
    ),
    (
        "moonshot",
        "changelog",
        "the platform changelog dates entries by month only, not by day",
    ),
    (
        "minimax",
        "product",
        "the product news page carries a single undated item",
    ),
    (
        "baidu",
        "cloud",
        "百度智能云's 更新动态 is the only dated page and is stale (2026-04-13)",
    ),
    (
        "zhipu",
        "developer",
        "the docs release notes are 404; news and research come from one source",
    ),
)


def unsupported_channels() -> tuple[tuple[str, str], ...]:
    """``(organization, channel)`` pairs that have no stable public source."""
    return tuple(
        (organization, channel)
        for organization, channel, _reason in UNSUPPORTED_CHANNELS
    )


def organization_map() -> dict[str, tuple[NewsSource, ...]]:
    """Every source grouped by the company that publishes it."""
    grouped: dict[str, list[NewsSource]] = {}
    for source in SOURCES:
        grouped.setdefault(source.organization, []).append(source)
    return {name: tuple(items) for name, items in grouped.items()}


def enabled_sources() -> tuple[NewsSource, ...]:
    return tuple(source for source in SOURCES if source.enabled)


def source_by_id(source_id: str) -> NewsSource:
    for source in SOURCES:
        if source.id == source_id:
            return source
    raise KeyError(source_id)


def source_map() -> dict[str, NewsSource]:
    return {source.id: source for source in SOURCES}
