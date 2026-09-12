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


class RefreshRunSummary(BaseModel):
    status: str
    trigger: str
    started_at: str
    finished_at: str | None
    # Preformatted in APP_TIMEZONE so the client never has to guess a timezone.
    local_time: str | None = None
    news_count: int
    github_count: int
    error: str | None = None


class RefreshStatus(BaseModel):
    scheduler_enabled: bool
    scheduler_running: bool
    timezone: str
    scheduled_time: str
    is_running: bool
    last_run: RefreshRunSummary | None = None
    next_run_at: str | None = None
