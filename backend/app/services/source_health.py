"""Per-source outcome reporting for one refresh.

The collectors already isolate failures, but the refresh report only printed a
count per source, which made "did Mistral break?" a question for the log or the
database. This module turns the per-source results into one aligned table: the
source, whether it succeeded, how many items it produced, and — when it failed —
what kind of failure it was.

Deliberately in-memory only. A source health *dashboard* would need persistence,
retention and a schema, none of which this phase needs; a refresh that prints
its own outcome is enough to notice a broken collector the same day. The
``consecutive_failures`` counter is therefore per-run: the CLI process starts at
zero and reports how many times a source failed while it was running.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

OK = "OK"
FAIL = "FAIL"

# Working sources print first, in the order the config declares them, and the
# failures follow together at the end of the table where they are easy to scan.
STATUS_ORDER = {OK: 0, FAIL: 1}

# Longest source name the column pads to; wider names simply push the columns.
MIN_NAME_WIDTH = 18

# Errors are classified, not echoed: a full HTTP client traceback in a table is
# noise. The categories match what the collectors actually raise.
FALLBACK_CLASSIFICATION = "error"
ERROR_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("timeout", re.compile(r"tim(e|ed) ?out|timeoutexception", re.IGNORECASE)),
    ("http 403", re.compile(r"\b403\b", re.IGNORECASE)),
    ("http 404", re.compile(r"\b404\b", re.IGNORECASE)),
    ("http 5xx", re.compile(r"\b5\d\d\b")),
    ("http", re.compile(r"\bHTTP \d{3}\b", re.IGNORECASE)),
    ("dns", re.compile(r"nameresolution|getaddrinfo|gaierror", re.IGNORECASE)),
    ("connection", re.compile(r"connect|network|unreachable|refused", re.IGNORECASE)),
    ("redirect", re.compile(r"redirect", re.IGNORECASE)),
    ("empty", re.compile(r"empty", re.IGNORECASE)),
    # A markup change reads as prose, not as a traceback: the HTML collectors
    # raise PageStructureError with messages like "no /blog/ links on the
    # Cohere blog", so the vocabulary those messages use is matched too.
    (
        "parse",
        re.compile(
            r"parse|structure|json|unreadable|unterminated"
            r"|article list|items array|links on the|is not a list|extractor for source",
            re.IGNORECASE,
        ),
    ),
)


@dataclass(frozen=True)
class SourceOutcome:
    """One source's result in one refresh."""

    source_id: str
    name: str
    success: bool
    fetched: int = 0
    # ``fetched`` is what the source published; ``valid`` is what survived the
    # collector's own checks and will enter the pipeline.
    valid: int = 0
    error: str | None = None

    @property
    def status(self) -> str:
        return OK if self.success else FAIL

    @property
    def error_type(self) -> str:
        """A short category for a failure, or an empty string on success."""
        if self.success:
            return ""
        text = (self.error or "").strip()
        if not text:
            return FALLBACK_CLASSIFICATION
        for label, pattern in ERROR_PATTERNS:
            if pattern.search(text):
                return label
        return FALLBACK_CLASSIFICATION

    def detail(self) -> str:
        """The third column: a count when it worked, an error type when not."""
        if self.success:
            return str(self.valid)
        return self.error_type


@dataclass
class SourceHealthReport:
    """Every source's outcome in one refresh, plus a per-source failure streak."""

    outcomes: list[SourceOutcome] = field(default_factory=list)
    # Counts failed attempts per source id *within this report*, so a caller that
    # keeps one report across retries can see a source fail repeatedly.
    failures: dict[str, int] = field(default_factory=dict)

    @property
    def failed(self) -> list[SourceOutcome]:
        return [outcome for outcome in self.outcomes if not outcome.success]

    @property
    def succeeded(self) -> list[SourceOutcome]:
        return [outcome for outcome in self.outcomes if outcome.success]

    def consecutive_failures(self, source_id: str) -> int:
        return self.failures.get(source_id, 0)

    @property
    def all_failed(self) -> bool:
        return bool(self.outcomes) and not self.succeeded

    def lines(self) -> list[str]:
        """The aligned table, one line per source, in a stable order."""
        if not self.outcomes:
            return []
        width = max(MIN_NAME_WIDTH, max(len(o.name) for o in self.outcomes) + 2)
        position = {id(outcome): index for index, outcome in enumerate(self.outcomes)}
        ordered = sorted(
            self.outcomes,
            key=lambda o: (STATUS_ORDER[o.status], position[id(o)]),
        )
        return [f"{o.name.ljust(width)}{o.status.ljust(8)}{o.detail()}" for o in ordered]

    def summary(self) -> str:
        ok = len(self.succeeded)
        return f"{ok}/{len(self.outcomes)} sources OK"


def classify_error(error: str | None) -> str:
    """Public wrapper over the same classification the table uses."""
    return SourceOutcome("", "", False, error=error).error_type


def build_report(reports) -> SourceHealthReport:
    """Turn collector results into a report. Accepts any CollectResult-like row."""
    health = SourceHealthReport()
    for report in reports:
        outcome = SourceOutcome(
            source_id=str(getattr(report, "source_id", "") or ""),
            name=str(getattr(report, "source_name", "") or getattr(report, "source_id", "")),
            success=bool(getattr(report, "success", False)),
            fetched=int(getattr(report, "fetched", 0) or 0),
            valid=len(getattr(report, "valid", []) or []),
            error=getattr(report, "error", None),
        )
        health.outcomes.append(outcome)
        if not outcome.success:
            health.failures[outcome.source_id] = health.failures.get(outcome.source_id, 0) + 1
    return health


def format_source_health(report: SourceHealthReport) -> str:
    """The refresh report block: a table plus one line naming what failed."""
    lines = ["Sources"] + report.lines()
    failed = report.failed
    if failed:
        lines.append("")
        lines.append(
            "Failed: "
            + ", ".join(f"{outcome.name} ({outcome.error_type})" for outcome in failed)
        )
    return "\n".join(lines)
