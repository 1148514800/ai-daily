from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.models import (
    DailyDigestGitHubRow,
    DailyDigestNewsRow,
    DailyDigestRow,
    FavoriteRow,
    GitHubProjectRow,
    NewsArticleRow,
    PushDeviceRow,
    RefreshRunRow,
    utcnow,
)
from app.models import GitHubProject, NewsCategory, NewsItem
from app.pipelines.urls import canonicalize_url

ITEM_TYPE_NEWS = "news"
ITEM_TYPE_GITHUB = "github"
VALID_ITEM_TYPES = (ITEM_TYPE_NEWS, ITEM_TYPE_GITHUB)

TRIGGER_MANUAL = "manual"
TRIGGER_SCHEDULED = "scheduled"
TRIGGER_STARTUP_CATCHUP = "startup_catchup"
VALID_TRIGGERS = (TRIGGER_MANUAL, TRIGGER_SCHEDULED, TRIGGER_STARTUP_CATCHUP)

RUN_RUNNING = "running"
RUN_SUCCESS = "success"
RUN_FAILED = "failed"

PLATFORM_ANDROID = "android"
VALID_PLATFORMS = (PLATFORM_ANDROID, "ios")


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _news_row_to_item(row: NewsArticleRow) -> NewsItem:
    return NewsItem(
        id=row.id,
        title_cn=row.title_cn,
        title_original=row.title_original,
        summary=row.summary,
        why_it_matters=row.why_it_matters,
        source=row.source,
        source_type=row.source_type,
        published_at=row.published_at.isoformat() if row.published_at else "",
        category=NewsCategory(row.category) if row.category else NewsCategory.highlight,
        tags=[row.source] if row.source else [],
        url=row.url,
        importance_score=row.importance_score,
    )


def _github_row_to_project(row: GitHubProjectRow) -> GitHubProject:
    try:
        topics = json.loads(row.topics_json or "[]")
    except (TypeError, ValueError):
        topics = []
    if not isinstance(topics, list):
        topics = []
    return GitHubProject(
        id=row.id,
        repo=row.repo,
        name=row.name,
        description=row.description,
        language=row.language,
        stars=row.stars,
        stars_delta=row.stars_delta,
        summary_cn=row.summary_cn,
        why_it_matters=row.why_it_matters,
        url=row.url,
        rank=row.rank,
        forks=row.forks,
        license=row.license,
        topics=[str(item) for item in topics],
    )


class NewsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_many(self, items: list[NewsItem]) -> int:
        """Insert or update news by stable ID. Returns the number of rows touched."""
        touched = 0
        for item in items:
            row = self.session.get(NewsArticleRow, item.id)
            canonical = canonicalize_url(item.url) if item.url else ""
            published = _parse_datetime(item.published_at)
            if row is None:
                self.session.add(
                    NewsArticleRow(
                        id=item.id,
                        title_cn=item.title_cn,
                        title_original=item.title_original,
                        summary=item.summary,
                        why_it_matters=item.why_it_matters,
                        source=item.source,
                        source_type=item.source_type,
                        published_at=published,
                        category=item.category.value,
                        url=item.url,
                        canonical_url=canonical,
                        importance_score=item.importance_score,
                    )
                )
            else:
                row.title_cn = item.title_cn
                row.title_original = item.title_original
                row.summary = item.summary
                row.why_it_matters = item.why_it_matters
                row.source = item.source
                row.source_type = item.source_type
                row.published_at = published
                row.category = item.category.value
                row.url = item.url
                row.canonical_url = canonical
                row.importance_score = item.importance_score
            touched += 1
        self.session.flush()
        return touched

    def get(self, news_id: str) -> NewsItem | None:
        row = self.session.get(NewsArticleRow, news_id)
        return _news_row_to_item(row) if row is not None else None

    def exists(self, news_id: str) -> bool:
        return self.session.get(NewsArticleRow, news_id) is not None

    def count(self) -> int:
        return int(self.session.scalar(select(func.count()).select_from(NewsArticleRow)) or 0)


class GitHubRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_many(self, projects: list[GitHubProject]) -> int:
        touched = 0
        for project in projects:
            row = self.session.get(GitHubProjectRow, project.id)
            topics_json = json.dumps(list(project.topics or []))
            if row is None:
                self.session.add(
                    GitHubProjectRow(
                        id=project.id,
                        repo=project.repo,
                        name=project.name,
                        description=project.description,
                        language=project.language,
                        stars=project.stars,
                        stars_delta=project.stars_delta,
                        summary_cn=project.summary_cn,
                        why_it_matters=project.why_it_matters,
                        url=project.url,
                        rank=project.rank,
                        forks=project.forks,
                        license=project.license,
                        topics_json=topics_json,
                    )
                )
            else:
                row.repo = project.repo
                row.name = project.name
                row.description = project.description
                row.language = project.language
                row.stars = project.stars
                row.stars_delta = project.stars_delta
                row.summary_cn = project.summary_cn
                row.why_it_matters = project.why_it_matters
                row.url = project.url
                row.rank = project.rank
                row.forks = project.forks
                row.license = project.license
                row.topics_json = topics_json
            touched += 1
        self.session.flush()
        return touched

    def get(self, project_id: str) -> GitHubProject | None:
        row = self.session.get(GitHubProjectRow, project_id)
        return _github_row_to_project(row) if row is not None else None

    def exists(self, project_id: str) -> bool:
        return self.session.get(GitHubProjectRow, project_id) is not None

    def list_all(self) -> list[GitHubProject]:
        rows = self.session.scalars(select(GitHubProjectRow)).all()
        return [_github_row_to_project(row) for row in rows]

    def count(self) -> int:
        return int(self.session.scalar(select(func.count()).select_from(GitHubProjectRow)) or 0)


class DigestRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(
        self,
        *,
        date: str,
        title: str,
        description: str,
        news_ids: list[str],
        github_ids: list[str],
    ) -> None:
        """Create or update one digest plus its ordering, in the caller's transaction."""
        row = self.session.get(DailyDigestRow, date)
        if row is None:
            row = DailyDigestRow(date=date, title=title, description=description)
            self.session.add(row)
        else:
            row.title = title
            row.description = description
        self.session.flush()

        # Replace the link rows so the final ordering for the day is exact.
        self.session.execute(delete(DailyDigestNewsRow).where(DailyDigestNewsRow.digest_date == date))
        self.session.execute(delete(DailyDigestGitHubRow).where(DailyDigestGitHubRow.digest_date == date))
        for position, news_id in enumerate(news_ids):
            self.session.add(DailyDigestNewsRow(digest_date=date, news_id=news_id, position=position))
        for position, github_id in enumerate(github_ids):
            self.session.add(DailyDigestGitHubRow(digest_date=date, github_project_id=github_id, position=position))
        self.session.flush()

    def mark_notified(self, date: str) -> bool:
        """Remember that a push for this digest already reached a device."""
        row = self.session.get(DailyDigestRow, date)
        if row is None:
            return False
        row.notified_at = utcnow()
        self.session.flush()
        return True

    def notified_at(self, date: str) -> datetime | None:
        row = self.session.get(DailyDigestRow, date)
        return row.notified_at if row is not None else None

    def needs_notification(self, date: str) -> bool:
        row = self.session.get(DailyDigestRow, date)
        if row is None:
            return False
        return row.notified_at is None

    def last_notified_at(self) -> datetime | None:
        return self.session.scalar(select(func.max(DailyDigestRow.notified_at)))

    def exists(self, date: str) -> bool:
        return self.session.get(DailyDigestRow, date) is not None

    def get_meta(self, date: str) -> tuple[str, str] | None:
        row = self.session.get(DailyDigestRow, date)
        if row is None:
            return None
        return row.title, row.description

    def get_news(self, date: str) -> list[NewsItem]:
        statement = (
            select(NewsArticleRow)
            .join(DailyDigestNewsRow, DailyDigestNewsRow.news_id == NewsArticleRow.id)
            .where(DailyDigestNewsRow.digest_date == date)
            .order_by(DailyDigestNewsRow.position)
        )
        return [_news_row_to_item(row) for row in self.session.scalars(statement).all()]

    def get_github(self, date: str) -> list[GitHubProject]:
        statement = (
            select(GitHubProjectRow)
            .join(DailyDigestGitHubRow, DailyDigestGitHubRow.github_project_id == GitHubProjectRow.id)
            .where(DailyDigestGitHubRow.digest_date == date)
            .order_by(DailyDigestGitHubRow.position)
        )
        return [_github_row_to_project(row) for row in self.session.scalars(statement).all()]

    def get_github_ids(self, date: str) -> list[str]:
        statement = (
            select(DailyDigestGitHubRow.github_project_id)
            .where(DailyDigestGitHubRow.digest_date == date)
            .order_by(DailyDigestGitHubRow.position)
        )
        return list(self.session.scalars(statement).all())

    def latest_date(self) -> str | None:
        return self.session.scalar(select(func.max(DailyDigestRow.date)))

    def list_summaries(self) -> list[tuple[str, str, int, int]]:
        """Return (date, title, news_count, github_count) ordered by date DESC."""
        statement = select(DailyDigestRow).order_by(DailyDigestRow.date.desc())
        rows = self.session.scalars(statement).all()
        summaries: list[tuple[str, str, int, int]] = []
        for row in rows:
            news_count = int(
                self.session.scalar(
                    select(func.count())
                    .select_from(DailyDigestNewsRow)
                    .where(DailyDigestNewsRow.digest_date == row.date)
                )
                or 0
            )
            github_count = int(
                self.session.scalar(
                    select(func.count())
                    .select_from(DailyDigestGitHubRow)
                    .where(DailyDigestGitHubRow.digest_date == row.date)
                )
                or 0
            )
            summaries.append((row.date, row.title, news_count, github_count))
        return summaries

    def count(self) -> int:
        return int(self.session.scalar(select(func.count()).select_from(DailyDigestRow)) or 0)


class FavoriteRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, item_type: str, item_id: str) -> tuple[FavoriteRow, bool]:
        """Return the favorite and whether it was newly created."""
        existing = self.session.scalar(
            select(FavoriteRow).where(FavoriteRow.item_type == item_type, FavoriteRow.item_id == item_id)
        )
        if existing is not None:
            return existing, False
        row = FavoriteRow(item_type=item_type, item_id=item_id)
        self.session.add(row)
        self.session.flush()
        return row, True

    def get(self, favorite_id: int) -> FavoriteRow | None:
        return self.session.get(FavoriteRow, favorite_id)

    def delete(self, favorite_id: int) -> bool:
        row = self.session.get(FavoriteRow, favorite_id)
        if row is None:
            return False
        self.session.delete(row)
        self.session.flush()
        return True

    def list_all(self) -> list[FavoriteRow]:
        statement = select(FavoriteRow).order_by(FavoriteRow.created_at.desc(), FavoriteRow.id.desc())
        return list(self.session.scalars(statement).all())

    def exists(self, item_type: str, item_id: str) -> bool:
        return (
            self.session.scalar(
                select(FavoriteRow).where(FavoriteRow.item_type == item_type, FavoriteRow.item_id == item_id)
            )
            is not None
        )

    def count(self) -> int:
        return int(self.session.scalar(select(func.count()).select_from(FavoriteRow)) or 0)


class RefreshRunRepository:
    """Tracks refresh attempts so failures are visible without log diving."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def start(self, trigger: str) -> RefreshRunRow:
        row = RefreshRunRow(trigger=trigger, status=RUN_RUNNING)
        self.session.add(row)
        self.session.flush()
        return row

    def finish(
        self,
        run_id: int,
        *,
        status: str,
        news_count: int = 0,
        github_count: int = 0,
        error: str | None = None,
        digest_date: str | None = None,
    ) -> RefreshRunRow | None:
        row = self.session.get(RefreshRunRow, run_id)
        if row is None:
            return None
        row.status = status
        row.news_count = news_count
        row.github_count = github_count
        row.error = error
        row.digest_date = digest_date
        row.finished_at = utcnow()
        self.session.flush()
        return row

    def latest(self) -> RefreshRunRow | None:
        statement = select(RefreshRunRow).order_by(RefreshRunRow.id.desc()).limit(1)
        return self.session.scalar(statement)

    def latest_for_date(self, date: str) -> RefreshRunRow | None:
        statement = (
            select(RefreshRunRow)
            .where(RefreshRunRow.digest_date == date)
            .order_by(RefreshRunRow.id.desc())
            .limit(1)
        )
        return self.session.scalar(statement)

    def has_success_for_date(self, date: str) -> bool:
        statement = (
            select(RefreshRunRow.id)
            .where(RefreshRunRow.digest_date == date, RefreshRunRow.status == RUN_SUCCESS)
            .limit(1)
        )
        return self.session.scalar(statement) is not None

    def list_recent(self, limit: int = 10) -> list[RefreshRunRow]:
        statement = select(RefreshRunRow).order_by(RefreshRunRow.id.desc()).limit(limit)
        return list(self.session.scalars(statement).all())

    def count(self) -> int:
        return int(self.session.scalar(select(func.count()).select_from(RefreshRunRow)) or 0)


class PushDeviceRepository:
    """Registration of Expo push tokens for the single-user app."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def register(self, expo_push_token: str, platform: str = PLATFORM_ANDROID) -> PushDeviceRow:
        """Upsert by token: re-registering a device refreshes it instead of duplicating."""
        row = self.session.scalar(
            select(PushDeviceRow).where(PushDeviceRow.expo_push_token == expo_push_token)
        )
        now = utcnow()
        if row is None:
            row = PushDeviceRow(
                expo_push_token=expo_push_token,
                platform=platform,
                enabled=True,
                created_at=now,
                last_seen_at=now,
            )
            self.session.add(row)
        else:
            row.platform = platform
            row.enabled = True
            row.last_seen_at = now
        self.session.flush()
        return row

    def get_by_token(self, expo_push_token: str) -> PushDeviceRow | None:
        return self.session.scalar(
            select(PushDeviceRow).where(PushDeviceRow.expo_push_token == expo_push_token)
        )

    def disable(self, expo_push_token: str) -> bool:
        """Turn notifications off without deleting the historical registration."""
        row = self.get_by_token(expo_push_token)
        if row is None:
            return False
        row.enabled = False
        self.session.flush()
        return True

    def disable_by_id(self, device_id: int) -> bool:
        row = self.session.get(PushDeviceRow, device_id)
        if row is None:
            return False
        row.enabled = False
        self.session.flush()
        return True

    def list_enabled(self) -> list[PushDeviceRow]:
        statement = (
            select(PushDeviceRow)
            .where(PushDeviceRow.enabled.is_(True))
            .order_by(PushDeviceRow.id)
        )
        return list(self.session.scalars(statement).all())

    def list_all(self) -> list[PushDeviceRow]:
        return list(self.session.scalars(select(PushDeviceRow).order_by(PushDeviceRow.id)).all())

    def count(self) -> int:
        return int(self.session.scalar(select(func.count()).select_from(PushDeviceRow)) or 0)

    def count_enabled(self) -> int:
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(PushDeviceRow)
                .where(PushDeviceRow.enabled.is_(True))
            )
            or 0
        )
