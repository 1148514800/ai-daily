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
    # The deterministic labels the ranking used for this article, reported so
    # the client shows the same topic instead of classifying again. Empty when
    # the article was read outside a digest and no label was computed.
    topic: str = ""
    company: str = ""
    # The original-language body. Excluded here on purpose: this model is also
    # the digest-list shape, and shipping every article body with the daily
    # digest would inflate the response the phone needs for a quick read. The
    # body leaves the backend only through ``NewsContent``.
    content_original: str = Field(default="", exclude=True)
    # What the body was cleaned from, kept for diagnosis and never served.
    content_raw: str = Field(default="", exclude=True)
    content_language: str = Field(default="", exclude=True)
    content_extraction_method: str = Field(default="", exclude=True)
    content_quality: str = Field(default="", exclude=True)
    content_fetched_at: str | None = Field(default=None, exclude=True)


class NewsDetail(NewsItem):
    """One article for the detail screen, deliberately *without* its body.

    Phase 10.11 made the body an on-demand fetch: the response says whether one
    exists (``has_content``) and how it was obtained, and the text itself comes
    from ``GET /news/{id}/content`` only when the reader taps 查看原文内容. The
    fields below describe the stored body; the body is not part of this payload.
    """

    has_content: bool = False
    content_language: str = ""
    content_extraction_method: str = ""
    content_quality: str = ""


class NewsContent(BaseModel):
    """The original-language body, returned only when it is asked for.

    ``content_original`` is the cleaned article text in the language it was
    published in: never translated, never summarised, never rewritten. When the
    backend could not extract a real body, this is the feed's own summary and
    ``content_quality`` says so instead of pretending.
    """

    news_id: str
    content_original: str
    content_language: str = ""
    content_extraction_method: str = ""
    content_quality: str = ""


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
