from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class NewsArticleRow(Base):
    __tablename__ = "news_articles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title_cn: Mapped[str] = mapped_column(Text, default="")
    title_original: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    why_it_matters: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(128), default="")
    source_type: Mapped[str] = mapped_column(String(64), default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    category: Mapped[str] = mapped_column(String(32), default="highlight")
    url: Mapped[str] = mapped_column(Text, default="")
    canonical_url: Mapped[str] = mapped_column(Text, default="")
    importance_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Original-language article body, extracted once and kept whole. It is never
    # translated: title_cn / summary / why_it_matters are separate Chinese fields
    # produced by the LLM, and neither side overwrites the other.
    content_original: Mapped[str] = mapped_column(Text, default="")
    content_language: Mapped[str] = mapped_column(String(16), default="")
    # How the body was obtained: rss_full / web / rss_summary / none.
    content_extraction_method: Mapped[str] = mapped_column(String(32), default="")
    content_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class GitHubProjectRow(Base):
    __tablename__ = "github_projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    repo: Mapped[str] = mapped_column(String(255), default="")
    name: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(64), default="")
    stars: Mapped[int] = mapped_column(Integer, default=0)
    stars_delta: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary_cn: Mapped[str] = mapped_column(Text, default="")
    why_it_matters: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(Text, default="")
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    forks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    license: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Topics are a small list, stored as a JSON array string to keep the API contract.
    topics_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class DailyDigestRow(Base):
    __tablename__ = "daily_digests"

    date: Mapped[str] = mapped_column(String(10), primary_key=True)
    title: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    # The issue window this digest covers, always stored in UTC. News is linked
    # by "window_start < published_at <= window_end" rather than by calendar day.
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set once a push for this digest reached at least one device, so retries and
    # restarts never notify the same day twice.
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class DailyDigestNewsRow(Base):
    __tablename__ = "daily_digest_news"
    __table_args__ = (UniqueConstraint("digest_date", "position", name="uq_digest_news_position"),)

    digest_date: Mapped[str] = mapped_column(
        String(10), ForeignKey("daily_digests.date", ondelete="CASCADE"), primary_key=True
    )
    news_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("news_articles.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)


class DailyDigestGitHubRow(Base):
    __tablename__ = "daily_digest_github"
    __table_args__ = (UniqueConstraint("digest_date", "position", name="uq_digest_github_position"),)

    digest_date: Mapped[str] = mapped_column(
        String(10), ForeignKey("daily_digests.date", ondelete="CASCADE"), primary_key=True
    )
    github_project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("github_projects.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)


class FavoriteRow(Base):
    __tablename__ = "favorites"
    __table_args__ = (UniqueConstraint("item_type", "item_id", name="uq_favorite_item"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_type: Mapped[str] = mapped_column(String(16), default="news")
    item_id: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RefreshRunRow(Base):
    """One refresh attempt. Kept small: short errors only, never secrets."""

    __tablename__ = "refresh_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trigger: Mapped[str] = mapped_column(String(32), default="manual")
    status: Mapped[str] = mapped_column(String(16), default="running")
    digest_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    news_count: Mapped[int] = mapped_column(Integer, default=0)
    github_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class PushDeviceRow(Base):
    """One registered device. Single-user app, so no user table yet."""

    __tablename__ = "push_devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    expo_push_token: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    platform: Mapped[str] = mapped_column(String(16), default="android")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
