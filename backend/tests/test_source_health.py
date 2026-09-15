"""Phase 10.11: the per-source refresh report.

Every refresh prints one line per source so "did Mistral break?" is answered by
the run itself instead of by a query later. The table is in-memory only; this
module pins its shape, its ordering and its error classification.
"""

from __future__ import annotations

from app.collectors.raw import CollectResult
from app.services.source_health import (
    FAIL,
    OK,
    classify_error,
    build_report,
    format_source_health,
)


def outcome(
    source_id: str,
    name: str,
    *,
    success: bool = True,
    valid: int = 0,
    error: str | None = None,
) -> CollectResult:
    result = CollectResult(source_id=source_id, source_name=name, success=success, error=error)
    result.valid = [object() for _ in range(valid)]
    return result


def test_the_report_matches_the_documented_table_shape() -> None:
    """The exact layout the phase promises, spacing included."""
    report = build_report(
        [
            outcome("openai", "OpenAI", valid=5),
            outcome("anthropic", "Anthropic", valid=4),
            outcome("mistral", "Mistral AI", valid=3),
            outcome("cohere", "Cohere", valid=2),
            outcome("microsoft-research", "Microsoft Research", valid=6),
            outcome("cursor", "Cursor", valid=4),
            outcome("ars-technica", "Ars Technica", valid=8),
            outcome("techcrunch-ai", "TechCrunch AI", valid=10),
        ]
    )

    assert format_source_health(report).splitlines() == [
        "Sources",
        "OpenAI              OK      5",
        "Anthropic           OK      4",
        "Mistral AI          OK      3",
        "Cohere              OK      2",
        "Microsoft Research  OK      6",
        "Cursor              OK      4",
        "Ars Technica        OK      8",
        "TechCrunch AI       OK      10",
    ]


def test_a_failure_prints_its_error_type_instead_of_a_count() -> None:
    report = build_report(
        [
            outcome("openai", "OpenAI", valid=5),
            outcome("mistral", "Mistral AI", success=False, error="timed out after 10s"),
        ]
    )

    assert format_source_health(report).splitlines() == [
        "Sources",
        "OpenAI            OK      5",
        "Mistral AI        FAIL    timeout",
        "",
        "Failed: Mistral AI (timeout)",
    ]


def test_working_sources_keep_their_config_order_and_failures_move_last() -> None:
    report = build_report(
        [
            outcome("a", "Broken", success=False, error="timeout"),
            outcome("b", "First", valid=1),
            outcome("c", "Second", valid=2),
        ]
    )

    names = [line.split()[0] for line in format_source_health(report).splitlines()[1:4]]
    assert names == ["First", "Second", "Broken"]


def test_the_count_column_reports_valid_articles_not_fetched_entries() -> None:
    """A feed can fetch twenty entries and keep three; the table says three."""
    result = outcome("ars-technica", "Ars Technica", valid=3)
    result.fetched = 20
    report = build_report([result])

    assert report.outcomes[0].fetched == 20
    assert format_source_health(report).splitlines()[1].endswith("3")


def test_error_classification_covers_the_failure_modes_collectors_raise() -> None:
    assert classify_error("HTTP 403 for https://x") == "http 403"
    assert classify_error("HTTP 500 server error") == "http 5xx"
    assert classify_error("NameResolutionError: getaddrinfo failed") == "dns"
    assert classify_error("Connection refused") == "connection"
    assert classify_error("Read timed out") == "timeout"
    assert classify_error("Empty HTML response") == "empty"
    assert classify_error("no /blog/ links on the Cohere blog") == "parse"
    assert classify_error("Redirect loop") == "redirect"


def test_an_unrecognised_failure_still_gets_a_category() -> None:
    assert classify_error("something new") == "error"
    assert classify_error("") == "error"


def test_a_mixed_run_is_summarised_without_hiding_the_failures() -> None:
    report = build_report(
        [
            outcome("a", "First", valid=1),
            outcome("b", "Second", success=False, error="timeout"),
            outcome("c", "Third", valid=2),
        ]
    )

    assert report.summary() == "2/3 sources OK"
    assert [item.name for item in report.failed] == ["Second"]
    assert report.all_failed is False
    assert report.consecutive_failures("b") == 1


def test_every_source_failing_is_visible_as_such() -> None:
    report = build_report(
        [outcome("a", "First", success=False, error="timeout"), outcome("b", "Second", success=False, error="dns")]
    )

    assert report.all_failed is True
    assert len(format_source_health(report).splitlines()[-1].split(",")) == 2


def test_an_empty_report_renders_no_table_at_all() -> None:
    assert format_source_health(build_report([])) == "Sources"


def test_status_constants_are_the_documented_words() -> None:
    assert (OK, FAIL) == ("OK", "FAIL")
