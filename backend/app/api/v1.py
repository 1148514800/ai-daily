from fastapi import APIRouter, HTTPException

from app.data.digests import DIGESTS_BY_DATE, TODAY_DATE
from app.data.github import GITHUB_PROJECTS
from app.data.news import NEWS_BY_ID
from app.models import DailyDigest, GitHubProject, NewsItem

router = APIRouter()


@router.get("/daily", response_model=DailyDigest)
def get_today_daily() -> DailyDigest:
    digest = DIGESTS_BY_DATE.get(TODAY_DATE)
    if digest is None:
        raise HTTPException(status_code=404, detail="Daily digest not found")
    return digest


@router.get("/daily/{date}", response_model=DailyDigest)
def get_daily_by_date(date: str) -> DailyDigest:
    digest = DIGESTS_BY_DATE.get(date)
    if digest is None:
        raise HTTPException(status_code=404, detail="Daily digest not found")
    return digest


@router.get("/news/{news_id}", response_model=NewsItem)
def get_news(news_id: str) -> NewsItem:
    item = NEWS_BY_ID.get(news_id)
    if item is None:
        raise HTTPException(status_code=404, detail="News item not found")
    return item


@router.get("/github", response_model=list[GitHubProject])
def list_github_projects() -> list[GitHubProject]:
    return GITHUB_PROJECTS
