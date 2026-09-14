"""Shared safety rail for maintenance commands that write the database.

``rebuild_search_index``, ``rebuild_digests``, ``backfill_article_content`` and
anything similar (a future repair or migrate task) all go through here, so the
same three questions are answered the same way every time:

1. *Which* database is this? ``--database-url`` > ``DATABASE_URL`` > the default.
2. Is that a target we may write to? Pointing at the production/default file, or
   running with ``APP_ENV=production``, refuses to continue without
   ``--allow-production``.
3. Can we still undo it? A production SQLite write is validated, backed up, and
   only then executed. A failed backup aborts the command before any write.

Every command prints the same header before it does anything:

    Environment: development
    Database:    <path>
    Mode:        execute

The database line is a resolved path, not a connection string, so no password
can leak from this output.
"""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from app.config.database_safety import (
    PRODUCTION_GUARD_MESSAGE,
    DatabaseTarget,
    describe_guard,
    resolve_target,
)
from app.config.env import BACKEND_ROOT
from app.config.environment import environment_label
from app.db.session import reset_database

logger = logging.getLogger(__name__)

BACKUP_DIR_NAME = "backups"
BACKUP_PREFIX = "pre"
# Overridable so a test (or an alternative deployment) can keep its backups
# somewhere other than the repository's own directory.
BACKUP_DIR_ENV = "AI_DAILY_BACKUP_DIR"

# Written to the console/exit status so a refusal is visible to a script.
EXIT_REFUSED = 2
EXIT_ABORTED = 3


class ProductionGuardError(RuntimeError):
    """The target looks like production and ``--allow-production`` was absent."""


class MaintenanceError(RuntimeError):
    """The command cannot safely continue (validation or backup failed)."""


@dataclass(frozen=True)
class MaintenanceContext:
    """A resolved, checked destination for one maintenance command."""

    command: str
    target: DatabaseTarget
    dry_run: bool
    allow_production: bool
    backup_dir: Path

    @property
    def environment(self) -> str:
        return self.target.environment

    @property
    def mode(self) -> str:
        return "dry-run" if self.dry_run else "execute"

    @property
    def is_production(self) -> bool:
        return self.target.is_production

    @property
    def backup_required(self) -> bool:
        """A real write to a production target is always backed up first."""
        return self.target.is_production and not self.dry_run


def add_common_arguments(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Add the arguments every database-writing maintenance command accepts.

    Called by each command so the flags cannot drift apart between jobs.
    """
    parser.add_argument(
        "--database-url",
        default=None,
        help=(
            "database to operate on, overriding DATABASE_URL "
            "(a sqlite:/// URL or a plain file path)"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would happen without changing any data",
    )
    parser.add_argument(
        "--allow-production",
        action="store_true",
        help="required before writing to the production/default database",
    )
    return parser


def normalize_url(value: str) -> str:
    r"""Accept a URL or a bare file path, and return a database URL.

    ``--database-url C:\temp\scratch.db`` is a natural thing to type, so a value
    without a scheme is treated as a SQLite file path.
    """
    raw = value.strip()
    if not raw:
        raise MaintenanceError("--database-url needs a value")
    if "://" in raw:
        return raw
    return f"sqlite:///{raw}"


def resolve_database_url(cli_value: str | None) -> str:
    """The database to use: CLI override, then the environment, then default.

    ``DATABASE_URL`` is read here rather than by ``app.db.session`` so the
    precedence is decided in one place and can be reported before use.
    """
    from app.config.database_safety import default_database_url

    if cli_value:
        return normalize_url(cli_value)
    from_env = os.getenv("DATABASE_URL", "").strip()
    if from_env:
        return from_env
    return default_database_url()


def point_at(url: str) -> DatabaseTarget:
    """Point this process at ``url`` and describe it. Writes no data.

    Shared by every command, including the read-only ones, so all of them report
    on - and read from - the same database the header names. A refused command
    never reaches this, so it cannot leave ``DATABASE_URL`` rewritten.
    """
    target = resolve_target(url)
    os.environ["DATABASE_URL"] = url
    reset_database()
    return target


def format_header(context: MaintenanceContext) -> str:
    """The lines every maintenance command prints before it does anything."""
    return (
        f"Environment: {environment_label()}\n"
        f"Database:    {context.target.display}\n"
        f"Mode:        {context.mode}"
    )


def begin(
    command: str,
    args: argparse.Namespace,
    *,
    backup_dir: Path | None = None,
) -> MaintenanceContext:
    """Resolve the target, print the header, and enforce the production guard.

    Raises ``ProductionGuardError`` when the target is production-like and
    ``--allow-production`` was not given. Nothing is written either way.
    """
    url = resolve_database_url(getattr(args, "database_url", None))
    target = resolve_target(url)
    context = MaintenanceContext(
        command=command,
        target=target,
        dry_run=bool(getattr(args, "dry_run", False)),
        allow_production=bool(getattr(args, "allow_production", False)),
        backup_dir=backup_dir or default_backup_dir(),
    )
    if target.is_production and not context.allow_production:
        if not context.dry_run:
            raise ProductionGuardError(describe_guard(target))
        # A dry run changes nothing, so it is allowed to *describe* work on the
        # production database. Reporting what would happen is exactly what the
        # guard is for; only the write itself needs --allow-production.
        print(
            "Note: this is the production/default database; a real run would "
            "require --allow-production."
        )

    # Only now point the process at it, so a refused command never touches the
    # database and never leaves DATABASE_URL rewritten.
    point_at(url)
    return context


def validate(context: MaintenanceContext) -> None:
    """Check the target can be safely written, before anything is changed.

    Reads only: a SQLite file that exists must pass ``PRAGMA integrity_check``.
    A target that does not exist yet has nothing to lose, so it passes and is
    reported as such.
    """
    path = context.target.path
    if path is None or not path.exists():
        return
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise MaintenanceError(f"cannot open {path}: {exc}") from exc
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.Error as exc:
        # "file is not a database" surfaces here rather than at connect(), so the
        # read is wrapped too: either way this aborts instead of writing.
        raise MaintenanceError(f"cannot read {path}: {exc}") from exc
    finally:
        connection.close()
    if not result or str(result[0]).lower() != "ok":
        raise MaintenanceError(
            f"integrity check failed on {path}: {result[0] if result else 'no result'}"
        )


def default_backup_dir() -> Path:
    """Where automatic backups go: ``<repo>/backups`` unless overridden."""
    raw = os.getenv(BACKUP_DIR_ENV, "").strip()
    if raw:
        path = Path(raw)
        return path if path.is_absolute() else (BACKEND_ROOT / path)
    return BACKEND_ROOT.parent / BACKUP_DIR_NAME


def backup_path(context: MaintenanceContext, *, moment: datetime | None = None) -> Path:
    """Where this run would put its backup, following the repo's naming."""
    stamp = (moment or datetime.now()).strftime("%Y%m%d_%H%M%S")
    name = f"{BACKUP_PREFIX}_{context.command}_{stamp}.db"
    return context.backup_dir / name


def backup(context: MaintenanceContext, *, moment: datetime | None = None) -> Path | None:
    """Copy the target aside before a production write.

    Returns the backup file, or None when no copy is needed (not a production
    target, a dry run, a non-file database, or a database that does not exist
    yet). Raises ``MaintenanceError`` when a copy was needed and failed, which
    the caller must treat as "do not write".
    """
    if not context.backup_required:
        return None
    if not context.target.is_sqlite:
        # PostgreSQL has no automatic file copy. Rather than write to a production
        # database we could not restore, the command stops here.
        raise MaintenanceError(
            f"automatic backup is unsupported for {context.target.backend} databases; "
            "only SQLite is copied before a write, so this command was stopped"
        )
    path = context.target.path
    if path is None:
        return None
    if not path.exists():
        print(f"Backup:      skipped, {path} does not exist yet")
        return None

    target = backup_path(context, moment=moment)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # The online backup API, not a file copy: it is consistent even while the
        # long-running backend still has the database open.
        source = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            destination = sqlite3.connect(target)
            try:
                source.backup(destination)
            finally:
                destination.close()
        finally:
            source.close()
    except (sqlite3.Error, OSError) as exc:
        raise MaintenanceError(
            f"backup failed ({exc.__class__.__name__}: {exc}); database left untouched"
        ) from exc
    print(f"Backup:      {target}")
    return target


def prepare_write(context: MaintenanceContext) -> Path | None:
    """``validate`` then ``backup``. The last step before an actual write."""
    validate(context)
    return backup(context)


SCHEMA_PRESENT = "present"
SCHEMA_ABSENT = "absent"
SCHEMA_UNKNOWN = "unknown"


def schema_state(target: DatabaseTarget) -> str:
    """Whether the target holds the application's tables: present/absent/unknown.

    A read-only question, asked so a dry run can say "this database is not
    initialised yet" instead of failing on a table that was never created. Any
    database that is not a readable SQLite file is reported as ``unknown`` rather
    than guessed at, so a non-SQLite target is never described as empty.
    """
    from app.db import readonly

    path = target.path
    if path is None:
        # A non-SQLite backend is not something we can read here, and an
        # in-memory SQLite database genuinely has no schema yet.
        return SCHEMA_ABSENT if target.is_sqlite else SCHEMA_UNKNOWN
    if not path.exists():
        return SCHEMA_ABSENT
    try:
        tables = readonly.table_names(path)
    except sqlite3.Error:
        return SCHEMA_UNKNOWN
    return SCHEMA_PRESENT if "news_articles" in tables else SCHEMA_ABSENT


__all__ = [
    "EXIT_ABORTED",
    "EXIT_REFUSED",
    "MaintenanceContext",
    "MaintenanceError",
    "PRODUCTION_GUARD_MESSAGE",
    "SCHEMA_ABSENT",
    "SCHEMA_PRESENT",
    "SCHEMA_UNKNOWN",
    "ProductionGuardError",
    "add_common_arguments",
    "backup",
    "backup_path",
    "default_backup_dir",
    "begin",
    "format_header",
    "point_at",
    "schema_state",
    "normalize_url",
    "prepare_write",
    "resolve_database_url",
    "validate",
]
