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
from typing import Iterable

from app.config.sources import NewsSource, source_map

OK = "OK"
FAIL = "FAIL"
# A source that answered but published nothing in this run, and a channel that
# has no stable public surface at all. They are distinct from each other and
# from a failure: "a quiet week" and "the page moved" are different facts, and
# reporting both as FAIL would hide the second behind the first.
EMPTY = "EMPTY"
UNSUPPORTED = "UNSUPPORTED"

# Working sources print first, in the order the config declares them, and the
# failures follow together at the end of the table where they are easy to scan.
# Ordering for the per-source table: what worked, then what published nothing,
# then what broke.
STATUS_ORDER = {OK: 0, EMPTY: 1, FAIL: 2}

# The coverage block orders organizations by how healthy their channels are, so
# a company with a broken channel is not buried under ones that are fine.
COVERAGE_STATUS_ORDER = {OK: 0, EMPTY: 1, FAIL: 2, UNSUPPORTED: 3}

# Widest status word the coverage block pads to ("UNSUPPORTED").
COVERAGE_STATUS_WIDTH = 12

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
    # Which company publishes this source and which of its official surfaces it
    # is. Carried here so the coverage block can group by company without
    # reaching back into the config for every row.
    organization: str = ""
    channel: str = "news"
    # True for the Web Discovery layer. It is a way of collecting rather than a
    # published source, so it appears in the per-source table like anything else
    # but must stay out of the official coverage: Tavily is not a company
    # channel, and counting it as one would overstate how much of a vendor's own
    # output AI Daily covers.
    discovery: bool = False

    @property
    def status(self) -> str:
        if not self.success:
            return FAIL
        # A source that answered with nothing is not broken, but it is also not
        # "working": reporting both as OK is what hides a channel that has gone
        # quiet — or a page whose markup changed to something still parseable.
        return EMPTY if self.valid == 0 else OK

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
        if not self.success:
            return self.error_type
        return str(self.valid)


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
    lookup = source_map()
    for report in reports:
        source_id = str(getattr(report, "source_id", "") or "")
        source = lookup.get(source_id)
        outcome = SourceOutcome(
            source_id=source_id,
            name=str(getattr(report, "source_name", "") or getattr(report, "source_id", "")),
            success=bool(getattr(report, "success", False)),
            fetched=int(getattr(report, "fetched", 0) or 0),
            valid=len(getattr(report, "valid", []) or []),
            error=getattr(report, "error", None),
            # Taken from the config rather than from the collector: a source's
            # company and channel are properties of the source, not of one run.
            organization=source.organization if source is not None else "",
            channel=source.channel if source is not None else "",
            discovery=bool(getattr(report, "discovery", False)),
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


@dataclass(frozen=True)
class CoverageRow:
    """One organization/channel pair and what it produced this run."""

    organization: str
    channel: str
    status: str
    source_name: str = ""
    # Empty for a channel that produced nothing, or for one that is known to
    # have no stable public source.
    valid: int = 0
    note: str = ""

def build_coverage(
    report: SourceHealthReport,
    *,
    unsupported: Iterable[tuple[str, str]] = (),
) -> list[CoverageRow]:
    """Group a run's outcomes by organization, then by channel.

    The per-source table answers "did this feed work"; this answers the question
    the phase is actually about — is a company covered on more than one official
    surface, and which of its channels is quiet or broken.

    ``unsupported`` carries the channels that have no stable public source at
    all, so the report states those explicitly instead of leaving a company
    looking fully covered because nothing failed.
    """
    rows = [
        CoverageRow(
            organization=outcome.organization or "unknown",
            channel=outcome.channel or "news",
            status=outcome.status,
            source_name=outcome.name,
            valid=outcome.valid,
        )
        for outcome in report.outcomes
        # Web discovery is a way of collecting, not somebody's official channel:
        # it is reported on its own and must not appear as a company surface.
        if not outcome.discovery
    ]
    for organization, channel in unsupported:
        rows.append(
            CoverageRow(
                organization=organization,
                channel=channel,
                status=UNSUPPORTED,
                note="no stable public source",
            )
        )
    rows.sort(
        key=lambda row: (
            row.organization,
            COVERAGE_STATUS_ORDER.get(row.status, 9),
            row.channel,
        )
    )
    return rows


def format_official_coverage(rows: list[CoverageRow]) -> str:
    """The organization/channel view of one run, grouped by company."""
    if not rows:
        return "Official Source Coverage"
    # One company can legitimately have two sources on the same kind of channel
    # (Google publishes two product blogs and two research blogs), so those rows
    # name the source as well; without it the block would print the same channel
    # twice with different counts and no way to tell them apart.
    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (row.organization, row.channel)
        counts[key] = counts.get(key, 0) + 1
    # The label is per row, not per channel: two sources of one company on the
    # same channel need their own names, and keying by channel would leave both
    # rows showing whichever name was written last.
    labels = [
        f"{row.channel} ({row.source_name})"
        if counts[(row.organization, row.channel)] > 1 and row.source_name
        else row.channel
        for row in rows
    ]
    channel_width = max(len(label) for label in labels) + 2
    lines = ["Official Source Coverage"]
    organization = None
    for row, label in zip(rows, labels):
        if row.organization != organization:
            organization = row.organization
            lines.append("")
            lines.append(organization)
        lines.append(
            f"  {label.ljust(channel_width)}"
            f"{row.status.ljust(COVERAGE_STATUS_WIDTH)}{row.note or row.valid}"
        )
    return "\n".join(lines)


def coverage_summary(rows: list[CoverageRow]) -> str:
    """One line: how many channels are OK, and how many are not OK."""
    ok = sum(1 for row in rows if row.status == OK)
    unsupported = sum(1 for row in rows if row.status == UNSUPPORTED)
    return (
        f"official coverage: {ok}/{len(rows)} channels OK"
        f", {unsupported} unsupported"
    )
