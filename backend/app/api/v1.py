from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from app.api.schemas import (
    DigestSummary,
    FavoriteCreate,
    FavoriteResponse,
    PushRegisterRequest,
    PushRegisterResponse,
    PushStatus,
    PushTestResult,
    RefreshRunSummary,
    RefreshStatus,
    SystemStatus,
)
from app.config.push import push_enabled
from app.config.schedule import scheduler_enabled
from app.config.timezone import app_timezone
from app.db.repositories import (
    VALID_ITEM_TYPES,
    PLATFORM_ANDROID,
    VALID_PLATFORMS,
    DigestRepository,
    FavoriteRepository,
    PushDeviceRepository,
    RefreshRunRepository,
)
from app.db.session import new_session
from app.jobs.daily_refresh import is_refresh_running
from app.jobs.scheduler import next_run_at, scheduler_state
from app.models import DailyDigest, GitHubProject, NewsDetail, NewsItem
from app.services.digest_store import store
from app.services.push import ExpoPushClient, PushMessage
from app.services.push.service import NOTIFICATION_TITLE

router = APIRouter()


@router.get("/daily", response_model=DailyDigest)
def get_today_daily() -> DailyDigest:
    return store.get_today()


@router.get("/digests", response_model=list[DigestSummary])
def list_digests() -> list[DigestSummary]:
    """Every stored digest, newest first. Lightweight: counts and window only."""
    return [
        DigestSummary(
            date=summary.date,
            title=summary.title,
            news_count=summary.news_count,
            github_count=summary.github_count,
            top_story_count=summary.top_story_count,
            window_start=_iso(summary.window_start),
            window_end=_iso(summary.window_end),
        )
        for summary in store.list_digest_summaries()
    ]


@router.get("/daily/{date}", response_model=DailyDigest)
def get_daily_by_date(date: str) -> DailyDigest:
    digest = store.get_by_date(date)
    if digest is None:
        raise HTTPException(status_code=404, detail="Daily digest not found")
    return digest


@router.get("/news/{news_id}", response_model=NewsDetail)
def get_news(news_id: str) -> NewsDetail:
    """One article with its original-language body.

    Every field the digest list returns is repeated here unchanged, so the
    detail response is a strict superset and older clients keep working. The
    body is the cleaned original text; Chinese ``title_cn`` / ``summary`` /
    ``why_it_matters`` are separate fields and never replace it.
    """
    item = store.get_news_detail(news_id)
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


@router.get("/refresh/status", response_model=RefreshStatus)
def get_refresh_status() -> RefreshStatus:
    """Expose scheduler state so the mobile app can show the last update time."""
    current = scheduler_state()
    session = new_session()
    try:
        latest = RefreshRunRepository(session).latest()
        finished_local = None
        if latest is not None and latest.finished_at is not None:
            finished = latest.finished_at
            if finished.tzinfo is None:
                finished = finished.replace(tzinfo=timezone.utc)
            finished_local = finished.astimezone(app_timezone()).strftime("%H:%M")
        last_run = (
            RefreshRunSummary(
                status=latest.status,
                trigger=latest.trigger,
                started_at=latest.started_at.isoformat() if latest.started_at else "",
                finished_at=latest.finished_at.isoformat() if latest.finished_at else None,
                local_time=finished_local,
                news_count=latest.news_count,
                github_count=latest.github_count,
                error=latest.error,
            )
            if latest is not None
            else None
        )
    finally:
        session.close()

    return RefreshStatus(
        scheduler_enabled=current.enabled,
        scheduler_running=current.running,
        timezone=current.timezone,
        scheduled_time=current.scheduled_time,
        is_running=is_refresh_running(),
        last_run=last_run,
        next_run_at=next_run_at(),
    )


@router.get("/system/status", response_model=SystemStatus)
def get_system_status() -> SystemStatus:
    """Deployment health check for the local long-running backend.

    Deliberately shallow: it reports that the API can reach SQLite and the
    scheduler configuration, without exposing connection strings or keys.
    """
    database = "ok"
    latest = None
    session = new_session()
    try:
        session.execute(text("SELECT 1"))
        latest = RefreshRunRepository(session).latest()
    except Exception:
        database = "error"
    finally:
        session.close()

    return SystemStatus(
        status="ok" if database == "ok" else "degraded",
        database=database,
        scheduler_enabled=scheduler_enabled(),
        last_refresh_status=latest.status if latest is not None else None,
        last_refresh_date=latest.digest_date if latest is not None else None,
    )


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


def _token_hint(token: str) -> str:
    """Never return a full push token to a client."""
    if len(token) <= 12:
        return "***"
    return f"{token[:10]}...{token[-4:]}"


def _iso(moment: datetime | None) -> str | None:
    """A stored timestamp as UTC ISO, or None. Reads stay uniform across routes."""
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat()


@router.post("/push/register", response_model=PushRegisterResponse)
def register_push_device(payload: PushRegisterRequest) -> PushRegisterResponse:
    """Upsert a device token. Re-registering refreshes the same row."""
    token = payload.expo_push_token.strip()
    if not token or not token.startswith("ExponentPushToken"):
        raise HTTPException(status_code=400, detail="Invalid Expo push token")
    platform = payload.platform.strip().lower() or PLATFORM_ANDROID
    if platform not in VALID_PLATFORMS:
        raise HTTPException(status_code=400, detail="Unsupported platform")

    session = new_session()
    try:
        row = PushDeviceRepository(session).register(token, platform)
        session.commit()
        return PushRegisterResponse(
            id=row.id,
            platform=row.platform,
            enabled=row.enabled,
            token_hint=_token_hint(row.expo_push_token),
        )
    finally:
        session.close()


@router.delete("/push/register", status_code=204)
def disable_push_device(expo_push_token: str = Query(...)) -> None:
    """Turn notifications off for a device while keeping its history."""
    session = new_session()
    try:
        if not PushDeviceRepository(session).disable(expo_push_token.strip()):
            raise HTTPException(status_code=404, detail="Device not found")
        session.commit()
    except HTTPException:
        session.rollback()
        raise
    finally:
        session.close()


@router.get("/push/status", response_model=PushStatus)
def get_push_status() -> PushStatus:
    session = new_session()
    try:
        devices = PushDeviceRepository(session)
        last_notified = DigestRepository(session).last_notified_at()
        return PushStatus(
            push_enabled=push_enabled(),
            registered_devices=devices.count(),
            enabled_devices=devices.count_enabled(),
            last_notified_at=last_notified.isoformat() if last_notified else None,
        )
    finally:
        session.close()


@router.post("/push/test", response_model=PushTestResult)
def send_test_push() -> PushTestResult:
    """Development-only helper. Sends a fixed test notification, never custom content."""
    if not push_enabled():
        raise HTTPException(status_code=403, detail="Push is disabled")

    session = new_session()
    try:
        devices = PushDeviceRepository(session).list_enabled()
    finally:
        session.close()
    if not devices:
        raise HTTPException(status_code=404, detail="No enabled devices")

    messages = [
        PushMessage(
            to=device.expo_push_token,
            title=NOTIFICATION_TITLE,
            body="AI Daily 测试通知",
            data={"type": "daily_digest"},
            channel_id="daily-digest",
        )
        for device in devices
    ]
    try:
        result = ExpoPushClient().send(messages)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Push request failed: {exc}") from exc

    if result.stale_tokens:
        cleanup = new_session()
        try:
            repository = PushDeviceRepository(cleanup)
            for token in result.stale_tokens:
                repository.disable(token)
            cleanup.commit()
        finally:
            cleanup.close()

    return PushTestResult(
        attempted=len(messages),
        delivered=result.delivered,
        failed=result.failed,
    )


def _resolve_favorite_item(session, item_type: str, item_id: str):
    if item_type == "news":
        from app.db.repositories import NewsRepository

        # Labelled so a favorite card shows a topic like a digest card does;
        # a favorite has no rank, so only the derived labels are added.
        return NewsRepository(session).get_labelled(item_id)
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
