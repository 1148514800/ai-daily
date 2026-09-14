"""Read-only report about the AI Daily database.

    uv run python -m app.jobs.inspect_database

This command never writes: no ``create_all``, no schema upgrade, no search index
creation, no ``VACUUM``, no data change. It opens the file read-only and prints
what is in it. Running it must not alter the file's SHA256, which the regression
test asserts and this job prints back so the claim is checkable by hand.

Usage:

    uv run python -m app.jobs.inspect_database
    uv run python -m app.jobs.inspect_database --database-url C:\\temp\\ai_daily.db
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.config.env import load_dotenv
from app.config.environment import environment_label
from app.config.maintenance import add_common_arguments, point_at, resolve_database_url
from app.db import readonly
from app.db.session import get_engine
from app.services.news_search import SEARCH_TABLE, backend_label, usable_backend

HISTOGRAM_LIMIT = 3

# The tables a reader cares about, in reading order. Reported even when the
# database predates one of them, so the report has a stable shape.
BUSINESS_TABLES = (
    "news_articles",
    "daily_digests",
    "daily_digest_news",
    "daily_digest_github",
    "github_projects",
    "favorites",
    "refresh_runs",
    "push_devices",
)


@dataclass
class Inspection:
    """Everything the report prints, gathered by read-only queries."""

    path: Path | None
    exists: bool
    size: int = 0
    sha256: str = ""
    integrity: str = "not checked"
    foreign_key_violations: list[tuple] = field(default_factory=list)
    counts: list[tuple[str, int | None]] = field(default_factory=list)
    fts_tables: list[str] = field(default_factory=list)
    fts_backend: str = ""


def inspect(path: Path) -> Inspection:
    """Read the facts about ``path``. Nothing here issues a write statement."""
    report = Inspection(path=path, exists=path.exists())
    if not report.exists:
        return report
    report.size = path.stat().st_size
    report.sha256 = readonly.file_sha256(path)
    report.integrity = readonly.integrity_check(path)
    report.foreign_key_violations = readonly.foreign_key_violations(path)
    report.fts_tables = readonly.index_tables(path, SEARCH_TABLE)
    report.fts_backend = backend_label(usable_backend(get_engine()))
    tables = readonly.table_names(path)
    report.counts = [
        (name, readonly.count_rows(path, name) if name in tables else None)
        for name in BUSINESS_TABLES
    ]
    return report


def format_report(report: Inspection) -> str:
    """The printed report, in the order a human reads it."""
    lines: list[str] = []
    if report.path is None:
        lines.append("Path:        (not a file database)")
        lines.append("SHA256:      n/a")
        lines.append("Integrity:   n/a")
        return "\n".join(lines)

    lines.append(f"Path:        {report.path}")
    if not report.exists:
        lines.append("Size:        (missing)")
        lines.append("SHA256:      n/a")
        lines.append("Integrity:   n/a")
        lines.append("")
        lines.append("The database file does not exist yet.")
        return "\n".join(lines)

    lines.append(f"Size:        {report.size} bytes ({readonly.human_size(report.size)})")
    lines.append(f"SHA256:      {report.sha256}")
    lines.append(f"Integrity:   {report.integrity}")

    violations = report.foreign_key_violations
    if not violations:
        lines.append("Foreign key check: ok")
    else:
        lines.append(f"Foreign key check: {len(violations)} violation(s)")
        for row in violations[:HISTOGRAM_LIMIT]:
            lines.append(f"  {row}")

    lines.append("")
    lines.append("Business table counts")
    for name, count in report.counts:
        lines.append(f"  {name}: {'(missing)' if count is None else count}")

    lines.append("")
    lines.append("FTS tables")
    if report.fts_tables:
        for name in report.fts_tables:
            lines.append(f"  {name}")
    else:
        lines.append("  (none)")
    lines.append(f"Search backend: {report.fts_backend}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only report about the AI Daily database"
    )
    add_common_arguments(parser)
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

    load_dotenv()
    url = resolve_database_url(args.database_url)
    # Point this process at the target so the search backend probe describes the
    # same database the report does. Nothing is written by doing so.
    target = point_at(url)

    print("Environment:", environment_label())
    print(f"Database:    {target.display}")
    print()
    print(format_report(inspect(target.path)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
