from fastapi import APIRouter, HTTPException

from app.models import DailyDigest, GitHubProject, NewsItem
from app.services.digest_store import store
from app.services.github_store import github_store

router = APIRouter()


@router.get("/daily", response_model=DailyDigest)
def get_today_daily() -> DailyDigest:
    return store.get_today()


@router.get("/daily/{date}", response_model=DailyDigest)
def get_daily_by_date(date: str) -> DailyDigest:
    digest = store.get_by_date(date)
    if digest is None:
        raise HTTPException(status_code=404, detail="Daily digest not found")
    return digest


@router.get("/news/{news_id}", response_model=NewsItem)
def get_news(news_id: str) -> NewsItem:
    item = store.get_news(news_id)
    if item is None:
        raise HTTPException(status_code=404, detail="News item not found")
    return item


@router.get("/github", response_model=list[GitHubProject])
def list_github_projects() -> list[GitHubProject]:
    return github_store.list_projects()
