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
