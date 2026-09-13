from enum import Enum

from pydantic import BaseModel, Field


class NewsCategory(str, Enum):
    highlight = "highlight"
    model = "model"
    opensource = "opensource"
    tool = "tool"


class NewsItem(BaseModel):
    id: str
    title_cn: str
    title_original: str
    summary: str
    why_it_matters: str
    source: str
    source_type: str
    published_at: str
    category: NewsCategory
    tags: list[str]
    url: str
    importance_score: int | None = None
    # Where this story ranked in the digest it was returned with, plus the score
    # that produced the order. Both are absent from an article read on its own
    # (a favorite, a detail lookup), because a rank only means something inside
    # one digest. ``is_top_story`` marks the leading stories the digest calls
    # out; the rest are still returned so nothing is hidden.
    rank: int | None = None
    rank_score: float | None = None
    is_top_story: bool | None = None
    # The original-language body. Excluded here on purpose: this model is also
    # the digest-list shape, and shipping every article body with the daily
    # digest would inflate the response the phone needs for a quick read.
    # ``NewsDetail`` re-declares the fields so the detail endpoint returns them.
    content_original: str = Field(default="", exclude=True)
    content_language: str = Field(default="", exclude=True)
    content_extraction_method: str = Field(default="", exclude=True)
    content_fetched_at: str | None = Field(default=None, exclude=True)


class NewsDetail(NewsItem):
    """One article with its original body, for the detail view.

    Every list field is inherited unchanged, so the detail response stays a
    superset of the list item and older clients keep working.
    """

    content_original: str = ""
    content_language: str = ""
    content_extraction_method: str = ""
    content_fetched_at: str | None = None


class GitHubProject(BaseModel):
    id: str
    repo: str
    name: str
    description: str
    language: str
    stars: int
    # Stars today from GitHub Trending HTML, not a historical snapshot delta.
    stars_delta: int | None = None
    summary_cn: str
    why_it_matters: str
    url: str
    rank: int | None = None
    forks: int | None = None
    license: str | None = None
    topics: list[str] = Field(default_factory=list)


class DailyDigest(BaseModel):
    date: str = Field(description="ISO date, YYYY-MM-DD")
    title: str
    description: str
    news: list[NewsItem]
    github_projects: list[GitHubProject]
    # The UTC issue window the digest covers: (window_start, window_end].
    # None for a digest written before windows existed.
    window_start: str | None = None
    window_end: str | None = None
