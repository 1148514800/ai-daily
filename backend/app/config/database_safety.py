"""Where a maintenance command is about to write, and whether that is safe.

Phase 10.9 ran ``rebuild_search_index`` with no ``DATABASE_URL`` set, so it
silently rewrote the real ``backend/data/ai_daily.db``. This module exists so
that can no longer happen by accident.

Two independent signals mark a target as production:

1. ``APP_ENV=production`` - the process says it is production;
2. the resolved database file *is* the default one, ``backend/data/ai_daily.db``.

The second is a sentinel that does not depend on the environment variable, so
mistyping ``APP_ENV=development`` on the production machine still refuses to
write. Nothing here writes to a database: this module only decides.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from app.config.env import BACKEND_ROOT
from app.config.environment import app_env

DEFAULT_DATABASE_FILE = BACKEND_ROOT / "data" / "ai_daily.db"

SQLITE_PREFIX = "sqlite:///"
SQLITE_MEMORY_URLS = ("sqlite://", "sqlite:///:memory:")

BACKEND_SQLITE = "sqlite"
BACKEND_OTHER = "other"

PRODUCTION_GUARD_MESSAGE = (
    "Target database looks like the production/default AI Daily database.\n"
    "Use --allow-production if intentional."
)


def default_database_url() -> str:
    """The URL used when neither the CLI nor the environment names one.

    Kept relative to the backend root (``sqlite:///./data/ai_daily.db``) so the
    repository stays machine independent. A default outside the backend root,
    which tests set, is expressed absolutely instead.
    """
    try:
        relative = DEFAULT_DATABASE_FILE.relative_to(BACKEND_ROOT)
    except ValueError:
        return f"{SQLITE_PREFIX}{DEFAULT_DATABASE_FILE.as_posix()}"
    return f"{SQLITE_PREFIX}./{relative.as_posix()}"


@dataclass(frozen=True)
class DatabaseTarget:
    """A resolved database destination, safe to print.

    ``display`` never carries a password: a PostgreSQL URL is shown without its
    credentials, because this string is written to logs and console output.
    """

    url: str
    display: str
    backend: str
    path: Path | None
    is_default: bool
    environment: str

    @property
    def is_sqlite(self) -> bool:
        return self.backend == BACKEND_SQLITE

    @property
    def is_production(self) -> bool:
        """Production by environment, or by pointing at the default file."""
        return self.environment == "production" or self.is_default

    @property
    def production_reason(self) -> str | None:
        if self.environment == "production" and self.is_default:
            return "APP_ENV=production and the default database file"
        if self.environment == "production":
            return "APP_ENV=production"
        if self.is_default:
            return "the default AI Daily database file"
        return None


def sqlite_path(url: str) -> Path | None:
    """The absolute file a SQLite URL points at, or None for anything else.

    An in-memory database has no path, and a PostgreSQL URL is not a file.
    """
    if not url.startswith(SQLITE_PREFIX):
        return None
    raw_path = url[len(SQLITE_PREFIX) :]
    if not raw_path or raw_path == ":memory:":
        return None
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = BACKEND_ROOT / raw_path
    return candidate.resolve()


def is_default_database(url: str) -> bool:
    """Whether ``url`` resolves to the default production database file.

    Compared by resolved path, so ``sqlite:///./data/ai_daily.db`` run from the
    backend directory and an absolute URL to the same file both match.
    """
    path = sqlite_path(url)
    if path is None:
        return False
    try:
        return path == DEFAULT_DATABASE_FILE.resolve()
    except OSError:  # pragma: no cover - resolve() only fails on bad volumes
        return False


def display_url(url: str) -> str:
    """A loggable form of a database URL, without any secret."""
    path = sqlite_path(url)
    if path is not None:
        return str(path)
    if url.startswith("sqlite"):
        return url
    parts = urlsplit(url)
    if not parts.scheme:
        return url
    netloc = parts.netloc
    if "@" in netloc:
        _, _, host = netloc.rpartition("@")
        netloc = f"***@{host}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def resolve_target(url: str) -> DatabaseTarget:
    """Describe a database URL without opening it."""
    path = sqlite_path(url)
    backend = BACKEND_SQLITE if url.startswith("sqlite") else BACKEND_OTHER
    return DatabaseTarget(
        url=url,
        display=display_url(url),
        backend=backend,
        path=path,
        is_default=is_default_database(url),
        environment=app_env(),
    )


def describe_guard(target: DatabaseTarget) -> str:
    """The refusal message for ``target``, naming why it was refused."""
    reason = target.production_reason or "an unknown reason"
    return f"{PRODUCTION_GUARD_MESSAGE}\nDetected because of: {reason}."
