"""Pre-release check: the things that must be true before shipping.

    uv run python -m app.jobs.release_check

Deliberately *not* a refresh: it makes no RSS request, no LLM request and no
database change. It opens the database read-only and reports PASS / WARN / FAIL
for the configuration and the data it finds.

Exit status is 0 when nothing failed and 1 when at least one check failed, so a
script can gate a release on it. Warnings alone do not fail the run.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.config.env import BACKEND_ROOT, load_dotenv
from app.config.environment import (
    APP_ENV_VALUES,
    app_env,
    configured_app_env,
    environment_label,
)
from app.config.maintenance import add_common_arguments, point_at, resolve_database_url
from app.config.schedule import (
    scheduler_enabled,
    scheduled_time_label,
)
from app.config.timezone import app_timezone, app_timezone_name
from app.db import readonly
from app.db.session import get_engine
from app.services.llm.settings import load_llm_settings
from app.services.news_search import BACKEND_LIKE, backend_label, usable_backend

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"

STATUS_ORDER = {FAIL: 0, WARN: 1, PASS: 2}

# Directories a deployment needs. Created by the app at runtime, so a missing one
# is a warning rather than a failure.
REQUIRED_DIRECTORIES = (
    ("data", BACKEND_ROOT / "data"),
    ("backups", BACKEND_ROOT.parent / "backups"),
    ("logs", BACKEND_ROOT.parent / "logs"),
)


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str = ""


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, status: str, detail: str = "") -> None:
        self.checks.append(Check(name=name, status=status, detail=detail))

    @property
    def failed(self) -> list[Check]:
        return [check for check in self.checks if check.status == FAIL]

    @property
    def warned(self) -> list[Check]:
        return [check for check in self.checks if check.status == WARN]

    @property
    def ok(self) -> bool:
        return not self.failed


def check_app_env(report: Report) -> None:
    raw = configured_app_env()
    if not raw:
        report.add("APP_ENV", WARN, f"unset, behaving as {app_env()}")
        return
    if raw not in APP_ENV_VALUES:
        report.add("APP_ENV", FAIL, f"unknown value {raw!r}; expected one of {', '.join(APP_ENV_VALUES)}")
        return
    report.add("APP_ENV", PASS, raw)


def check_timezone(report: Report) -> None:
    name = app_timezone_name()
    try:
        app_timezone()
    except Exception as exc:
        report.add("APP_TIMEZONE", FAIL, f"{name!r} is not a usable timezone: {exc}")
        return
    report.add("APP_TIMEZONE", PASS, name)


def check_scheduler(report: Report) -> None:
    if not scheduler_enabled():
        report.add(
            "Scheduler",
            WARN,
            "SCHEDULER_ENABLED=false: the digest will not refresh on its own",
        )
        return
    report.add(
        "Scheduler",
        PASS,
        f"daily at {scheduled_time_label()} ({app_timezone_name()})",
    )


def check_llm(report: Report) -> None:
    settings = load_llm_settings()
    if not settings.enabled:
        report.add("LLM", PASS, "disabled; the digest keeps the original text")
        return
    missing = [
        name
        for name, value in (
            ("LLM_API_KEY", settings.api_key),
            ("LLM_MODEL", settings.model),
            ("LLM_BASE_URL", settings.base_url),
        )
        if not value
    ]
    if missing:
        report.add("LLM", FAIL, f"enabled but missing {', '.join(missing)}")
        return
    # Never print key or endpoint: an enabled LLM is all this needs to confirm.
    report.add("LLM", PASS, f"enabled, model configured (timeout {settings.timeout:g}s)")


def check_directories(report: Report) -> None:
    missing = [name for name, path in REQUIRED_DIRECTORIES if not path.exists()]
    if missing:
        report.add("Directories", WARN, f"missing (created on demand): {', '.join(missing)}")
        return
    report.add("Directories", PASS, ", ".join(name for name, _ in REQUIRED_DIRECTORIES))


def check_database(report: Report, path: Path | None, url: str) -> None:
    if path is None:
        report.add("Database", WARN, "not a SQLite file database; integrity not checked here")
        return
    if not path.exists():
        report.add("Database", WARN, f"{path} does not exist yet; it is created on first run")
        return
    # A file that is not a database at all raises rather than returning a
    # verdict; that is a failure to report, not a crash to propagate.
    try:
        integrity = readonly.integrity_check(path)
    except Exception as exc:
        report.add("Database integrity", FAIL, f"unreadable: {exc.__class__.__name__}")
        report.add("Foreign keys", FAIL, "not checked: the database could not be read")
        return
    if integrity.lower() != "ok":
        report.add("Database integrity", FAIL, integrity)
    else:
        report.add("Database integrity", PASS, f"{path.name} ok")

    try:
        violations = readonly.foreign_key_violations(path)
    except Exception as exc:
        report.add("Foreign keys", FAIL, f"not checked: {exc.__class__.__name__}")
        return
    if violations:
        report.add("Foreign keys", FAIL, f"{len(violations)} violation(s)")
    else:
        report.add("Foreign keys", PASS, "no violations")


def check_search(report: Report) -> None:
    try:
        backend = usable_backend(get_engine())
    except Exception as exc:
        report.add("Search backend", FAIL, f"could not be determined: {exc.__class__.__name__}")
        return
    if backend == BACKEND_LIKE:
        report.add("Search backend", WARN, "SQL LIKE fallback (FTS5 unavailable)")
        return
    report.add("Search backend", PASS, backend_label(backend))


def check_production_safety(report: Report, path: Path | None) -> None:
    """Report the guard the maintenance jobs will apply to this database."""
    guard_env = os.getenv("APP_ENV", "").strip().lower()
    if guard_env == "production":
        report.add(
            "Production safety",
            WARN,
            "APP_ENV=production: maintenance jobs require --allow-production",
        )
        return
    report.add("Production safety", PASS, "maintenance jobs guard the production database")


def run_checks(url: str, path: Path | None) -> Report:
    report = Report()
    check_app_env(report)
    check_timezone(report)
    check_scheduler(report)
    check_llm(report)
    check_directories(report)
    check_database(report, path, url)
    check_search(report)
    check_production_safety(report, path)
    return report


def format_report(report: Report) -> str:
    width = max((len(check.name) for check in report.checks), default=0)
    lines = [f"{check.status}  {check.name.ljust(width)}  {check.detail}".rstrip() for check in report.checks]
    lines.append("")
    failed = len(report.failed)
    warned = len(report.warned)
    if failed:
        lines.append(f"{failed} check(s) failed, {warned} warning(s)")
    elif warned:
        lines.append(f"All checks passed ({warned} warning(s))")
    else:
        lines.append("All checks passed")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pre-release checks for the AI Daily backend")
    add_common_arguments(parser)
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

    load_dotenv()
    url = resolve_database_url(args.database_url)
    target = point_at(url)

    print("AI Daily release check")
    print("Environment:", environment_label())
    print(f"Database:    {target.display}")
    print()
    report = run_checks(url, target.path)
    print(format_report(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
