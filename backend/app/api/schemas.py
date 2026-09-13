from pydantic import BaseModel

from app.models import GitHubProject, NewsItem


class DigestSummary(BaseModel):
    """One row of the history list.

    Deliberately counts only: the history screen needs to know a day exists and
    how big it was, never what was in it. Shipping the stories here would make
    the list as heavy as opening every digest at once.
    """

    date: str
    title: str
    news_count: int
    github_count: int
    # How many of ``news_count`` the digest calls out as top stories, so the list
    # can say "10 条重点" without loading the digest.
    top_story_count: int
    # The UTC issue window the digest covers, for debugging and for a client that
    # wants to know why two days do not overlap. Null for a pre-window digest.
    window_start: str | None = None
    window_end: str | None = None


class FavoriteCreate(BaseModel):
    item_type: str
    item_id: str


class SearchResultItem(BaseModel):
    """One search hit.

    Carries what a result row shows — title, snippet, source, date, labels — and
    deliberately **not** the article body: search can return dozens of rows, and
    shipping every body would make the list as heavy as opening each article.
    The body is still one tap away via ``GET /api/v1/news/{id}``.
    """

    news_id: str
    title_cn: str
    original_title: str
    summary: str
    source: str
    published_at: str
    # The digest this article was published in, or null when it never reached one
    # (an article whose timestamp is still ahead of every window).
    digest_date: str | None = None
    topic: str = ""
    company: str = ""
    snippet: str = ""


class SearchResponse(BaseModel):
    query: str
    total: int
    items: list[SearchResultItem]


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
