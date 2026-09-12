from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
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
