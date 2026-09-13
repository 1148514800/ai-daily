from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.config.env import load_dotenv

DEFAULT_TIMEZONE = "Asia/Shanghai"
DIGEST_DATE_FORMAT = "%Y-%m-%d"


def app_timezone_name() -> str:
    import os

    load_dotenv()
    return os.getenv("APP_TIMEZONE", "").strip() or DEFAULT_TIMEZONE


def app_timezone() -> ZoneInfo:
    return ZoneInfo(app_timezone_name())


def digest_date_for(moment: datetime) -> str:
    """Return the digest date (YYYY-MM-DD) for an instant, in APP_TIMEZONE.

    Naive datetimes are treated as UTC, matching how collectors store times.
    """
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(app_timezone()).strftime(DIGEST_DATE_FORMAT)


def digest_date_for_iso(value: str) -> str | None:
    """Return the digest date for a stored ISO timestamp.

    None means the timestamp is missing or unparseable, so callers can treat it
    as belonging to no day instead of crashing. Naive values are read as UTC,
    which is how published_at is stored.
    """
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return digest_date_for(moment)


def today_digest_date() -> str:
    return digest_date_for(datetime.now(timezone.utc))
