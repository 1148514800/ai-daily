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


class PushRegisterRequest(BaseModel):
    expo_push_token: str
    platform: str = "android"


class PushRegisterResponse(BaseModel):
    id: int
    platform: str
    enabled: bool
    # Masked on purpose: the status endpoints never echo a full token.
    token_hint: str


class PushStatus(BaseModel):
    push_enabled: bool
    registered_devices: int
    enabled_devices: int
    last_notified_at: str | None = None


class PushTestResult(BaseModel):
    attempted: int
    delivered: int
    failed: int
    skipped_reason: str | None = None
    error: str | None = None


class SystemStatus(BaseModel):
    """Deployment health summary. Never includes secrets or connection strings."""

    status: str
    database: str
    scheduler_enabled: bool
    last_refresh_status: str | None = None
    last_refresh_date: str | None = None
