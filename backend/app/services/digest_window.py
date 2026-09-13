"""Issue windows decide which news belongs to a daily digest.

A digest covers the half-open interval ``(window_start, window_end]`` in UTC,
not a calendar day. The window runs from the previous successful cutoff to the
current refresh time, so a digest generated at 08:00 contains everything
published since the last one, and a missed day is picked up on the next run
instead of silently falling back to a fixed 24h lookback.

The interval is left-open to keep adjacent digests disjoint: an article on the
boundary belongs to exactly one digest.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.config.schedule import daily_refresh_hour, daily_refresh_minute
from app.config.timezone import DIGEST_DATE_FORMAT, app_timezone

DEFAULT_WINDOW_HOURS = 24


def as_utc(moment: datetime) -> datetime:
    """Read a naive datetime as UTC, matching how timestamps are stored."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def parse_timestamp(value: str | None) -> datetime | None:
    """Parse a stored ISO timestamp into an aware UTC datetime."""
    if not value:
        return None
    try:
        return as_utc(datetime.fromisoformat(value))
    except ValueError:
        return None


def is_future(published_at: datetime | str | None, now: datetime) -> bool:
    """True when an article is published after ``now``.

    A future timestamp must never be a candidate, however the window was
    derived. This keeps the fix that ``now - published_at <= 24h`` alone could
    not express, because that condition is also satisfied by a negative delta.
    """
    if isinstance(published_at, str):
        published_at = parse_timestamp(published_at)
    if published_at is None:
        return False
    return as_utc(published_at) > as_utc(now)


@dataclass(frozen=True)
class DigestWindow:
    """The half-open interval ``(start, end]`` a digest is responsible for."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "start", as_utc(self.start))
        object.__setattr__(self, "end", as_utc(self.end))

    @property
    def valid(self) -> bool:
        return self.start < self.end

    def contains(self, published_at: datetime | str | None) -> bool:
        """True when an instant falls inside the window.

        This is the single membership rule: ``start < published_at <= end``.
        ``start`` is exclusive so consecutive digests never share an article,
        and ``end`` is inclusive but never later than the refresh time, which
        keeps future-dated articles out.
        """
        if isinstance(published_at, str):
            published_at = parse_timestamp(published_at)
        if published_at is None:
            return False
        return self.start < as_utc(published_at) <= self.end


def first_window(now: datetime, *, hours: int = DEFAULT_WINDOW_HOURS) -> DigestWindow:
    """The window for the very first digest: the last ``hours`` before now."""
    current = as_utc(now)
    return DigestWindow(start=current - timedelta(hours=hours), end=current)


def continuing_window(previous_end: datetime, now: datetime) -> DigestWindow:
    """The window for a new digest: from the last successful cutoff to now."""
    return DigestWindow(start=as_utc(previous_end), end=as_utc(now))


def resolve_window(
    *,
    now: datetime,
    existing_start: datetime | None = None,
    previous_end: datetime | None = None,
    hours: int = DEFAULT_WINDOW_HOURS,
) -> DigestWindow:
    """Pick the window for a refresh.

    ``existing_start`` wins so a second refresh on the same day keeps extending
    its original window instead of restarting from the new cutoff, and
    ``previous_end`` continues from the last successful digest. Without either,
    the first digest falls back to the last ``hours`` before now.
    """
    current = as_utc(now)
    candidate: DigestWindow | None = None
    if existing_start is not None:
        candidate = DigestWindow(start=existing_start, end=current)
    elif previous_end is not None:
        candidate = continuing_window(previous_end, current)

    # A stale or future cutoff (clock skew, manual backfill) must not produce an
    # inverted window, so fall back to the default lookback instead.
    if candidate is None or not candidate.valid:
        return first_window(current, hours=hours)
    return candidate


def scheduled_cutoff(date: str) -> datetime:
    """The UTC instant of the daily cutoff on a local ``date`` (YYYY-MM-DD)."""
    local = datetime.strptime(date, DIGEST_DATE_FORMAT).replace(
        hour=daily_refresh_hour(),
        minute=daily_refresh_minute(),
        tzinfo=app_timezone(),
    )
    return local.astimezone(timezone.utc)


def historical_window(date: str) -> DigestWindow:
    """Derive the window a digest dated ``date`` should have had.

    Historical digests are rebuilt from the configured daily cutoff, so the
    interval is one day long: ``(cutoff(previous day), cutoff(date)]``.
    """
    start_local = datetime.strptime(date, DIGEST_DATE_FORMAT) - timedelta(days=1)
    return DigestWindow(
        start=scheduled_cutoff(start_local.strftime(DIGEST_DATE_FORMAT)),
        end=scheduled_cutoff(date),
    )
