from dataclasses import dataclass, field
from datetime import datetime

from app.models import NewsItem


@dataclass
class CollectResult:
    """What one source produced in a single collection run.

    Every collector, RSS or HTML, returns this shape so the pipeline and the
    per-source failure isolation never need to know how a source was read.
    """

    source_id: str = ""
    source_name: str = ""
    success: bool = True
    fetched: int = 0
    valid: list["RawArticle"] = field(default_factory=list)
    skipped: int = 0
    news_items: list[NewsItem] = field(default_factory=list)
    error: str | None = None
    # True for the Web Discovery layer, which is a way of *collecting* and not a
    # source. The refresh report prints it like any other row, but the official
    # source coverage must not count it as a company channel, so it is flagged
    # here rather than re-derived from the source id at each call site.
    discovery: bool = False


@dataclass(frozen=True)
class RawArticle:
    source_id: str
    source: str
    source_type: str
    title: str
    url: str
    canonical_url: str
    published_at: datetime | None
    summary: str
    # The body the feed itself carries (RSS ``content:encoded``, Atom
    # ``content``). Empty when the feed only publishes a short description.
    feed_body: str = ""
    # Filled in by the article extraction step, in the article's own language.
    # Kept separate from ``summary``, which the LLM turns into Chinese prose.
    content: str = ""
    # The candidate text ``content`` was cleaned from, before the noise rules
    # dropped navigation / cookie / share lines. Diagnosis only: never served.
    content_raw: str = ""
    content_language: str = ""
    content_method: str = ""
    # The deterministic verdict on ``content``: good / low / fallback. Empty when
    # no body was extracted at all.
    content_quality: str = ""
    content_fetched_at: datetime | None = None


@dataclass(frozen=True)
class RawTrendingRepo:
    rank: int
    repo: str
    name: str
    description: str
    language: str
    url: str
    stars: int
    stars_today: int | None
