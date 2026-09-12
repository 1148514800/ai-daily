from pydantic import BaseModel

from app.models import GitHubProject, NewsItem


class DigestSummary(BaseModel):
    date: str
    title: str
    news_count: int
    github_count: int


class FavoriteCreate(BaseModel):
    item_type: str
    item_id: str


class FavoriteNewsItem(BaseModel):
    item_type: str = "news"
    item: NewsItem


class FavoriteGitHubItem(BaseModel):
    item_type: str = "github"
    item: GitHubProject


class FavoriteResponse(BaseModel):
    id: int
    item_type: str
    created_at: str
    item: NewsItem | GitHubProject
