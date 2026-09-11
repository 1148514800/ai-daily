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
    stars_delta: int
    summary_cn: str
    why_it_matters: str
    url: str


class DailyDigest(BaseModel):
    date: str = Field(description="ISO date, YYYY-MM-DD")
    title: str
    description: str
    news: list[NewsItem]
    github_projects: list[GitHubProject]
