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
