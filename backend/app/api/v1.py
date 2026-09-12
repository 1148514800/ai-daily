from fastapi import APIRouter, HTTPException, Query

from app.api.schemas import DigestSummary, FavoriteCreate, FavoriteResponse
from app.db.repositories import VALID_ITEM_TYPES, FavoriteRepository
from app.db.session import new_session
from app.models import DailyDigest, GitHubProject, NewsItem
from app.services.digest_store import store

router = APIRouter()


@router.get("/daily", response_model=DailyDigest)
def get_today_daily() -> DailyDigest:
    return store.get_today()


@router.get("/digests", response_model=list[DigestSummary])
def list_digests() -> list[DigestSummary]:
    return [
        DigestSummary(date=date, title=title, news_count=news_count, github_count=github_count)
        for date, title, news_count, github_count in store.list_digest_summaries()
    ]


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
def list_github_projects(date: str | None = Query(default=None)) -> list[GitHubProject]:
    """Return GitHub projects for a digest date, defaulting to the latest digest."""
    target = date or store.latest_date()
    if target is None:
        return []
    return store.get_github_projects(target)


@router.get("/favorites", response_model=list[FavoriteResponse])
def list_favorites() -> list[FavoriteResponse]:
    session = new_session()
    try:
        return [_format_favorite(session, row) for row in FavoriteRepository(session).list_all()]
    finally:
        session.close()


@router.post("/favorites", response_model=FavoriteResponse, status_code=201)
def create_favorite(payload: FavoriteCreate) -> FavoriteResponse:
    if payload.item_type not in VALID_ITEM_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported item_type")

    session = new_session()
    try:
        if _resolve_favorite_item(session, payload.item_type, payload.item_id) is None:
            raise HTTPException(status_code=404, detail="Favorite target not found")
        row, _created = FavoriteRepository(session).add(payload.item_type, payload.item_id)
        session.commit()
        # Duplicate favorites return the existing row instead of creating one.
        return _format_favorite(session, row)
    except HTTPException:
        session.rollback()
        raise
    finally:
        session.close()


@router.delete("/favorites/{favorite_id}", status_code=204)
def delete_favorite(favorite_id: int) -> None:
    session = new_session()
    try:
        if not FavoriteRepository(session).delete(favorite_id):
            raise HTTPException(status_code=404, detail="Favorite not found")
        session.commit()
    except HTTPException:
        session.rollback()
        raise
    finally:
        session.close()


def _resolve_favorite_item(session, item_type: str, item_id: str):
    if item_type == "news":
        from app.db.repositories import NewsRepository

        return NewsRepository(session).get(item_id)
    from app.db.repositories import GitHubRepository

    return GitHubRepository(session).get(item_id)


def _format_favorite(session, row) -> FavoriteResponse:
    item = _resolve_favorite_item(session, row.item_type, row.item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Favorite target not found")
    return FavoriteResponse(
        id=row.id,
        item_type=row.item_type,
        created_at=row.created_at.isoformat() if row.created_at else "",
        item=item,
    )
