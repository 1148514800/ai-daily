from __future__ import annotations

import os
from zoneinfo import ZoneInfo

from app.config.env import load_dotenv
from app.config.timezone import app_timezone_name

DEFAULT_REFRESH_HOUR = 8
DEFAULT_REFRESH_MINUTE = 0
DEFAULT_MISFIRE_GRACE_SECONDS = 3600
DEFAULT_RETRY_DELAY_MINUTES = 15
DAILY_REFRESH_JOB_ID = "daily-refresh"


def _env_bool(name: str, default: bool) -> bool:
    load_dotenv()
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    load_dotenv()
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if value < minimum or value > maximum:
        return default
    return value


def scheduler_enabled() -> bool:
    """Gate both the daily job and the startup catch-up.

    Turning this off keeps the API working but stops all automatic refreshes,
    so tests can drive refreshes explicitly.
    """
    return _env_bool("SCHEDULER_ENABLED", True)


def daily_refresh_hour() -> int:
    return _env_int("DAILY_REFRESH_HOUR", DEFAULT_REFRESH_HOUR, minimum=0, maximum=23)


def daily_refresh_minute() -> int:
    return _env_int("DAILY_REFRESH_MINUTE", DEFAULT_REFRESH_MINUTE, minimum=0, maximum=59)


def misfire_grace_seconds() -> int:
    return DEFAULT_MISFIRE_GRACE_SECONDS


def retry_delay_minutes() -> int:
    return DEFAULT_RETRY_DELAY_MINUTES


def scheduled_time_label() -> str:
    return f"{daily_refresh_hour():02d}:{daily_refresh_minute():02d}"


def schedule_timezone() -> ZoneInfo:
    return ZoneInfo(app_timezone_name())
