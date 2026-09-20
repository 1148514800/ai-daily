"""Tests for the Baidu Web Search probe.

The probe is allowed to call the real API exactly once, by hand, from
``python -m app.jobs.test_baidu_search``. The suite must not: every test here
feeds a fixed response through the injected transport, so running pytest never
spends Baidu free quota and never depends on the network.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.jobs import test_baidu_search as probe
from app.jobs.test_baidu_search import (
    ENDPOINT,
    QUERY_POOL,
    Attempt,
    build_payload,
    check_query,
    describe_failure,
    domain_of,
    error_message,
    find_result_list,
    format_publish_time,
    is_known_source_domain,
    is_within_last_24h,
    known_source_domains,
    main,
    parse_page_time,
    parse_search_response,
    probe_date_range,
    run,
    send_request,
    summarize,
    to_search_result,
)

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
INSIDE = "2026-09-20 06:00:00"
OUTSIDE = "2026-09-18 06:00:00"


@pytest.fixture(autouse=True)
def ignore_the_developers_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the probe's ``main()`` from reading the real ``backend/.env``.

    ``main()`` calls ``load_dotenv()``, which fills in any variable the process
    does not already have - so a developer who really does have a
    ``BAIDU_SEARCH_API_KEY`` would make the "no key configured" tests pass a key
    in and fail. Tests must not depend on the machine they run on, and every value
    they need is set explicitly, so the loader is a no-op here.
    """
    monkeypatch.setattr(probe, "load_dotenv", lambda *args, **kwargs: None)


def entry(**kwargs) -> dict:
    """One documented web result entry."""
    node = {
        "title": "OpenAI 发布新模型",
        "url": "https://openai.com/news/x",
        "website": "openai.com",
        "page_time": INSIDE,
        "snippet": "OpenAI 发布了新模型。",
    }
    node.update(kwargs)
    return node


def body(*entries, key: str = "references", **extra) -> dict:
    payload = {"requestId": "abc", key: list(entries)}
    payload.update(extra)
    return payload


def ok(*entries) -> Attempt:
    payload = body(*entries)
    return Attempt(status_code=200, payload=payload, raw_text=json.dumps(payload))


def collect(attempt: Attempt, query: str = "q") -> list:
    parsed = parse_search_response(attempt.payload)
    known = known_source_domains()
    return [to_search_result(raw, query, known) for raw in parsed.results]


# --------------------------------------------------------------------------- #
# request
# --------------------------------------------------------------------------- #


def test_payload_asks_for_web_results_with_a_date_range() -> None:
    payload = build_payload("AI Agent 最新发布", "2026-09-19", "2026-09-20")
    assert payload["messages"] == [{"role": "user", "content": "AI Agent 最新发布"}]
    assert payload["search_source"] == "baidu_search_v2"
    assert payload["edition"] == "standard"
    assert payload["sort"] == {"priority": "auto"}
    assert payload["resource_type_filter"] == [{"type": "web", "top_k": probe.DEFAULT_TOP_K}]
    assert payload["search_filter"]["range"]["page_time"] == {"gte": "2026-09-19", "lte": "2026-09-20"}


def test_payload_never_asks_for_video_image_or_aladdin() -> None:
    types = [item["type"] for item in build_payload("q", "2026-09-19", "2026-09-20")["resource_type_filter"]]
    assert types == ["web"]


def test_probe_date_range_is_yesterday_through_today_in_app_timezone() -> None:
    assert probe_date_range(NOW) == ("2026-09-19", "2026-09-20")


def test_probe_date_range_follows_the_local_clock_not_utc() -> None:
    """20:00 UTC is already the next day in Asia/Shanghai, so 'today' moves."""
    assert probe_date_range(datetime(2026, 9, 19, 20, 0, tzinfo=timezone.utc)) == ("2026-09-19", "2026-09-20")


def test_endpoint_is_the_official_baidu_search_api() -> None:
    assert ENDPOINT == "https://qianfan.baidubce.com/v2/ai_search/web_search"
    assert ENDPOINT.startswith("https://")


def test_query_pool_holds_the_ten_planned_queries() -> None:
    assert len(QUERY_POOL) == 10
    assert len(set(QUERY_POOL)) == 10
    assert "AI Agent 最新发布" in QUERY_POOL


def test_over_long_query_is_skipped_locally() -> None:
    reason = check_query("A" * 100, 72)
    assert "100 characters" in reason
    assert "72 character limit" in reason
    assert check_query("AI Agent 最新发布", 72) == ""

# --------------------------------------------------------------------------- #
# parsing
# --------------------------------------------------------------------------- #


def test_parses_a_normal_response() -> None:
    parsed = parse_search_response(body(entry()))
    assert parsed.found
    assert parsed.list_key == "references"
    assert len(parsed.results) == 1
    result = parsed.results[0]
    assert result.title == "OpenAI 发布新模型"
    assert result.url == "https://openai.com/news/x"
    assert result.published == INSIDE
    assert result.snippet == "OpenAI 发布了新模型。"


def test_parses_multiple_results_in_order() -> None:
    payload = body(
        entry(title="first", url="https://a.example.com/1"),
        entry(title="second", url="https://b.example.com/2"),
        entry(title="third", url="https://c.example.com/3"),
    )
    results = parse_search_response(payload).results
    assert [result.title for result in results] == ["first", "second", "third"]


def test_empty_result_list_is_a_reading_success_with_no_results() -> None:
    parsed = parse_search_response(body())
    assert parsed.found is True
    assert parsed.results == []


def test_a_response_without_a_result_list_is_reported_as_a_failure() -> None:
    parsed = parse_search_response({"requestId": "abc", "references_total": 0})
    assert parsed.found is False


def test_alternative_result_list_keys_are_accepted() -> None:
    for key in ("results", "web_results", "items", "docs"):
        parsed = parse_search_response({key: [entry()]})
        assert parsed.found, key
        assert parsed.list_key == key


def test_a_non_object_entry_is_never_returned_as_a_result() -> None:
    parsed = parse_search_response({"references": [entry(), "not a result", 42]})
    assert len(parsed.results) == 1


def test_an_entry_without_a_url_is_dropped_and_counted() -> None:
    parsed = parse_search_response(body(entry(url=""), entry(url="")))
    assert parsed.results == []
    assert parsed.skipped_no_url == 2


def test_missing_fields_do_not_sink_the_response() -> None:
    payload = body({"url": "https://example.com/only-url"})
    parsed = parse_search_response(payload)
    assert len(parsed.results) == 1
    assert parsed.results[0].title == ""
    assert parsed.results[0].snippet == ""
    assert parsed.results[0].published == ""


def test_result_list_nested_under_another_key_is_found() -> None:
    nodes, key = find_result_list({"data": {"references": [entry()]}})
    assert nodes is not None
    assert key == "data.references"


# --------------------------------------------------------------------------- #
# publish time
# --------------------------------------------------------------------------- #


def test_parse_page_time_reads_iso_timestamps() -> None:
    assert parse_page_time("2026-09-20 06:00:00").moment == datetime(2026, 9, 20, 6, 0, tzinfo=timezone(timedelta(hours=8)))
    assert parse_page_time("2026-09-20T06:00:00+08:00").has_time is True


def test_parse_page_time_reads_a_bare_date_without_inventing_a_time() -> None:
    value = parse_page_time("2026-09-19")
    assert value.raw == "2026-09-19"
    assert value.moment is not None
    assert value.has_time is False


def test_parse_page_time_reads_the_chinese_date_form() -> None:
    assert parse_page_time("2026年09月19日").has_time is False
    with_time = parse_page_time("2026年09月19日 08:30")
    assert with_time.has_time is True
    assert with_time.moment.hour == 8 and with_time.moment.minute == 30


def test_parse_page_time_reads_epoch_seconds_and_milliseconds() -> None:
    expected = datetime(2026, 9, 20, 6, 0, tzinfo=timezone.utc)
    assert parse_page_time(int(expected.timestamp())).moment == expected
    assert parse_page_time(int(expected.timestamp() * 1000)).moment == expected


def test_unparseable_publish_time_stays_unknown_and_keeps_its_text() -> None:
    value = parse_page_time("3小时前")
    assert value.moment is None
    assert value.has_time is False
    assert value.raw == "3小时前"
    assert "unparsed" in format_publish_time(value)


def test_missing_publish_time_is_unknown_not_epoch() -> None:
    for raw in (None, "", "   "):
        value = parse_page_time(raw)
        assert value.moment is None
        assert value.raw == ""
    assert format_publish_time(parse_page_time(None)) == "(unknown)"


def test_format_publish_time_marks_a_date_only_value() -> None:
    assert format_publish_time(parse_page_time("2026-09-19")).endswith("(date only)")


def test_is_within_last_24h_accepts_recent_and_rejects_old() -> None:
    assert is_within_last_24h(datetime(2026, 9, 20, 6, 0, tzinfo=timezone.utc), NOW)
    assert not is_within_last_24h(datetime(2026, 9, 18, 6, 0, tzinfo=timezone.utc), NOW)
    assert is_within_last_24h(None, NOW) is False


def test_is_within_last_24h_excludes_future_timestamps() -> None:
    assert not is_within_last_24h(datetime(2026, 9, 21, 6, 0, tzinfo=timezone.utc), NOW)


def test_the_window_is_strict_at_the_24h_boundary() -> None:
    assert is_within_last_24h(NOW - timedelta(hours=24), NOW)
    assert not is_within_last_24h(NOW - timedelta(hours=24, seconds=1), NOW)


# --------------------------------------------------------------------------- #
# domains
# --------------------------------------------------------------------------- #


def test_domain_of_strips_www_and_lowercases() -> None:
    assert domain_of("https://WWW.OpenAI.com/news/x") == "openai.com"
    assert domain_of("https://developer.nvidia.com/blog/x") == "developer.nvidia.com"
    assert domain_of("not a url") == ""


def test_known_source_domains_come_from_the_source_config() -> None:
    known = known_source_domains()
    assert "openai.com" in known
    assert "techcrunch.com" in known
    assert all(domain == domain.lower() for domain in known)


def test_configured_source_domain_is_known() -> None:
    known = known_source_domains()
    assert is_known_source_domain("openai.com", known)
    assert is_known_source_domain("arstechnica.com", known)


def test_subdomains_of_a_configured_source_are_known() -> None:
    known = known_source_domains()
    assert is_known_source_domain("blog.openai.com", known)


def test_a_parent_of_a_configured_subdomain_is_known() -> None:
    """nvidia.com is the parent of the configured developer.nvidia.com."""
    known = known_source_domains()
    assert is_known_source_domain("nvidia.com", known)


def test_unrelated_domains_are_not_known() -> None:
    known = known_source_domains()
    assert not is_known_source_domain("nytimes.com", known)
    assert not is_known_source_domain("openai.com.evil.example", known)
    assert not is_known_source_domain("myopenai.com", known)
    assert not is_known_source_domain("", known)

# --------------------------------------------------------------------------- #
# transport and failure reporting
# --------------------------------------------------------------------------- #


def test_send_request_never_raises_on_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    transport = httpx.MockTransport(handler)
    original = httpx.Client

    class Patched(original):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    httpx.Client = Patched
    try:
        attempt = send_request(ENDPOINT, {}, {"messages": []}, 5.0)
    finally:
        httpx.Client = original
    assert attempt.status_code is None
    assert "timed out" in attempt.transport_error
    assert "timed out" in describe_failure(attempt)


def test_send_request_never_raises_on_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*args, **kwargs):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(httpx, "Client", explode)
    attempt = send_request(ENDPOINT, {}, {"messages": []}, 5.0)
    assert attempt.transport_error.startswith("connection failed")


def test_send_request_reports_a_non_json_body(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        status_code = 200
        text = "<html>gateway</html>"

        def json(self):
            raise ValueError("no json here")

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)
    attempt = send_request(ENDPOINT, {}, {"messages": []}, 5.0)
    assert attempt.status_code == 200
    assert attempt.parsed is False
    assert "not JSON" in describe_failure(attempt)


def test_401_is_reported_as_a_rejected_key() -> None:
    payload = {"code": 216003, "message": "get authorization error"}
    attempt = Attempt(status_code=401, payload=payload, raw_text=json.dumps(payload))
    message = describe_failure(attempt)
    assert "API key was rejected" in message
    assert "get authorization error" in message


def test_403_is_reported_as_a_rejected_key() -> None:
    attempt = Attempt(status_code=403, payload={"message": "forbidden"})
    assert "API key was rejected" in describe_failure(attempt)


def test_429_is_reported_without_retrying() -> None:
    attempt = Attempt(status_code=429, payload={"message": "quota exceeded"})
    message = describe_failure(attempt)
    assert "rate limited" in message
    assert "does not retry" in message


def test_400_is_reported_as_a_rejected_request() -> None:
    attempt = Attempt(status_code=400, payload={"message": "invalid resource_type_filter"})
    message = describe_failure(attempt)
    assert "HTTP 400" in message
    assert "invalid resource_type_filter" in message


@pytest.mark.parametrize("status", [500, 502, 503])
def test_5xx_is_reported_as_a_baidu_failure(status: int) -> None:
    attempt = Attempt(status_code=status, payload={"message": "internal error"})
    message = describe_failure(attempt)
    assert f"HTTP {status}" in message
    assert "Baidu failed" in message


def test_a_200_without_a_results_list_names_the_schema_that_came_back() -> None:
    payload = {"request_id": "x", "webSearchResult": []}
    attempt = Attempt(status_code=200, payload=payload, raw_text=json.dumps(payload))
    message = describe_failure(attempt)
    assert "no results list" in message
    assert "request_id" in message and "webSearchResult" in message


def test_error_message_reads_both_baidu_error_shapes() -> None:
    assert error_message({"code": 216003, "message": "get authorization error"}) == "get authorization error (code 216003)"
    assert error_message({"error_code": 336000, "error_msg": "bad request"}) == "bad request (code 336000)"
    assert error_message({"error": {"message": "unauthorized"}}) == "unauthorized"
    assert error_message({"error": "plain text"}) == "plain text"
    assert error_message("not a dict") == ""
    assert error_message({}) == ""


# --------------------------------------------------------------------------- #
# dedupe and statistics
# --------------------------------------------------------------------------- #


def outcome(query: str, *entries) -> probe.QueryOutcome:
    result = probe.QueryOutcome(query=query, attempt=ok(*entries))
    result.results = collect(ok(*entries), query)
    return result


def test_the_same_url_from_two_queries_is_counted_once() -> None:
    shared = entry(url="https://example.com/same")
    summary = summarize([outcome("q1", shared), outcome("q2", shared)], NOW)
    assert summary.raw_results == 2
    assert summary.unique_urls == 1
    assert summary.duplicates == 1


def test_tracking_parameters_do_not_create_a_second_result() -> None:
    summary = summarize(
        [
            outcome("q1", entry(url="https://example.com/x?utm_source=baidu")),
            outcome("q2", entry(url="https://example.com/x")),
        ],
        NOW,
    )
    assert summary.unique_urls == 1
    assert summary.duplicates == 1


def test_different_urls_stay_separate() -> None:
    summary = summarize(
        [outcome("q1", entry(url="https://example.com/a"), entry(url="https://example.com/b"))],
        NOW,
    )
    assert summary.unique_urls == 2
    assert summary.duplicates == 0


def test_summary_counts_known_and_discovered_hostnames() -> None:
    summary = summarize(
        [
            outcome(
                "q1",
                entry(url="https://openai.com/news/x"),
                entry(url="https://nytimes.com/ai/story"),
            )
        ],
        NOW,
    )
    assert summary.known_sources == 1
    assert summary.discovered == 1


def test_summary_counts_recency_buckets() -> None:
    summary = summarize(
        [
            outcome(
                "q1",
                entry(url="https://a.example.com/1", page_time=INSIDE),
                entry(url="https://b.example.com/2", page_time=OUTSIDE),
                entry(url="https://c.example.com/3", page_time=""),
            ),
        ],
        NOW,
    )
    assert summary.published_known == 2
    assert summary.inside_24h == 1
    assert summary.outside_24h == 1
    assert summary.unknown_publish == 1


def test_a_date_only_publish_time_is_not_judged_as_inside_24h() -> None:
    """The date is real, the moment is not, so it must not claim a 24h result."""
    summary = summarize([outcome("q1", entry(page_time="2026-09-20"))], NOW)
    assert summary.published_known == 1
    assert summary.inside_24h == 0
    assert summary.inside_24h + summary.outside_24h == 0
    assert summary.unknown_publish == 1


def test_unique_domains_counts_hostnames_not_urls() -> None:
    summary = summarize(
        [
            outcome(
                "q1",
                entry(url="https://a.example.com/1"),
                entry(url="https://a.example.com/2"),
                entry(url="https://b.example.com/3"),
            )
        ],
        NOW,
    )
    assert summary.unique_urls == 3
    assert summary.unique_domains == 2


def test_failed_and_skipped_queries_are_counted_separately() -> None:
    failed = probe.QueryOutcome(query="q2", attempt=Attempt(status_code=500, payload={}))
    failed.error = describe_failure(failed.attempt)
    skipped = probe.QueryOutcome(query="q3", skipped="too long")
    summary = summarize([outcome("q1", entry()), failed, skipped], NOW)
    assert summary.queries == 3
    assert summary.successful == 1
    assert summary.failed == 1
    assert summary.skipped == 1


def test_irrelevant_results_are_counted_without_being_dropped() -> None:
    irrelevant = entry(
        title="Best espresso machines of 2026",
        url="https://coffee.example.com/best-machines",
        snippet="We tested 12 machines.",
    )
    summary = summarize([outcome("q1", irrelevant, entry())], NOW)
    assert len(summary.irrelevant) == 1
    assert summary.unique_urls == 2

# --------------------------------------------------------------------------- #
# run loop
# --------------------------------------------------------------------------- #


class Recorder:
    """Collects the probe's terminal output so it can be asserted on."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, line: str) -> None:
        self.lines.append(line)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def fake_send(responses: dict, calls: list | None = None):
    """A transport that answers by query and records what it was asked."""

    def send(url: str, headers: dict, payload: dict, timeout: float) -> Attempt:
        query = payload["messages"][0]["content"]
        if calls is not None:
            calls.append({"url": url, "headers": headers, "payload": payload, "timeout": timeout})
        return responses[query]

    return send


def test_run_sends_one_request_per_query_and_uses_the_documented_endpoint() -> None:
    calls: list = []
    send = fake_send({query: ok(entry(url=f"https://example.com/{index}")) for index, query in enumerate(QUERY_POOL)}, calls)
    status = run(api_key="secret", queries=QUERY_POOL, now=NOW, send=send, out=Recorder())
    assert status == 0
    assert len(calls) == len(QUERY_POOL)
    assert all(call["url"] == ENDPOINT for call in calls)
    assert all(call["headers"]["Authorization"] == "Bearer secret" for call in calls)
    assert all(call["payload"]["search_filter"]["range"]["page_time"]["lte"] == "2026-09-20" for call in calls)


def test_run_keeps_going_after_one_query_fails() -> None:
    responses = {query: ok(entry(url=f"https://example.com/{index}")) for index, query in enumerate(QUERY_POOL)}
    responses["AI Agent 最新发布"] = Attempt(status_code=500, payload={"message": "boom"})
    calls: list = []
    status = run(
        api_key="secret",
        queries=QUERY_POOL,
        now=NOW,
        send=fake_send(responses, calls),
        out=Recorder(),
    )
    assert len(calls) == len(QUERY_POOL)
    assert status == 0


def test_run_reports_failed_and_successful_queries() -> None:
    queries = ("good", "bad")
    responses = {"good": ok(entry()), "bad": Attempt(status_code=429, payload={"message": "slow down"})}
    recorder = Recorder()
    run(api_key="secret", queries=queries, now=NOW, send=fake_send(responses), out=recorder)
    assert "Successful: 1" in recorder.text
    assert "Failed: 1" in recorder.text
    assert "QUERY: bad" in recorder.text


def test_run_never_sends_an_over_long_query() -> None:
    long_query = "AI " * 60
    calls: list = []
    recorder = Recorder()
    run(
        api_key="secret",
        queries=(long_query,),
        now=NOW,
        send=fake_send({}, calls),
        out=recorder,
    )
    assert calls == []
    assert "SKIPPED" in recorder.text
    assert "Skipped (over the query length limit): 1" in recorder.text


def test_run_prints_the_required_header_without_the_key() -> None:
    recorder = Recorder()
    run(
        api_key="super-secret-key",
        queries=("q",),
        now=NOW,
        send=fake_send({"q": ok(entry())}),
        out=recorder,
    )
    assert "Baidu Web Search Probe" in recorder.text
    assert f"Endpoint: {ENDPOINT}" in recorder.text
    assert "API key: configured" in recorder.text
    assert "super-secret-key" not in recorder.text


def test_run_prints_summary_counts() -> None:
    recorder = Recorder()
    run(
        api_key="secret",
        queries=("q1", "q2"),
        now=NOW,
        send=fake_send(
            {
                "q1": ok(entry(url="https://openai.com/news/x")),
                "q2": ok(entry(url="https://example.com/new")),
            }
        ),
        out=recorder,
    )
    for expected in (
        "SUMMARY",
        "Raw results: 2",
        "Unique URLs: 2",
        "Duplicate URLs: 0",
        "Published time available: 2",
        "Inside last 24h: 2",
        "Unique domains: 2",
        "Known fixed-source URLs: 1",
        "New/discovered URLs: 1",
        "Top domains:",
    ):
        assert expected in recorder.text, expected


def test_each_query_is_printed_exactly_once() -> None:
    """Per-query output happens as the query finishes, not again in the summary."""
    recorder = Recorder()
    run(
        api_key="secret",
        queries=("q1", "q2"),
        now=NOW,
        send=fake_send(
            {
                "q1": ok(entry(url="https://example.com/1")),
                "q2": ok(entry(url="https://example.com/2")),
            }
        ),
        out=recorder,
    )
    assert recorder.text.count("QUERY: q1") == 1
    assert recorder.text.count("QUERY: q2") == 1
    assert recorder.text.count("SUMMARY") == 1


def test_run_prints_no_result_as_an_empty_list_not_an_error() -> None:
    recorder = Recorder()
    status = run(api_key="secret", queries=("q",), now=NOW, send=fake_send({"q": ok()}), out=recorder)
    assert status == 0
    assert "Results: 0" in recorder.text


def test_run_exits_unusable_when_no_query_succeeds() -> None:
    recorder = Recorder()
    attempt = Attempt(status_code=401, payload={"message": "get authorization error"})
    status = run(api_key="bad", queries=("q1", "q2"), now=NOW, send=fake_send({"q1": attempt, "q2": attempt}), out=recorder)
    assert status == 1
    assert "Successful: 0" in recorder.text
    assert "Failed: 2" in recorder.text


def test_run_separates_known_from_discovered_in_the_report() -> None:
    recorder = Recorder()
    run(
        api_key="secret",
        queries=("q",),
        now=NOW,
        send=fake_send(
            {
                "q": ok(
                    entry(url="https://openai.com/news/x"),
                    entry(title="A brand new robotics lab", url="https://newlab.example.com/post"),
                )
            }
        ),
        out=recorder,
    )
    assert "DISCOVERED CANDIDATES" in recorder.text
    assert "newlab.example.com" in recorder.text


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #


def test_main_without_a_key_reports_the_missing_variable_and_exits_cleanly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.delenv("BAIDU_SEARCH_API_KEY", raising=False)
    status = main([])
    captured = capsys.readouterr()
    assert status == 2
    assert "Missing environment variable: BAIDU_SEARCH_API_KEY" in captured.out
    assert "Traceback" not in captured.out
    assert "Traceback" not in captured.err


def test_main_does_not_call_the_api_when_the_key_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BAIDU_SEARCH_API_KEY", raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("the probe must not send a request without a key")

    monkeypatch.setattr(probe, "send_request", forbidden)
    assert main([]) == 2


def test_a_blank_key_counts_as_missing(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setenv("BAIDU_SEARCH_API_KEY", "   ")
    assert main([]) == 2
    assert "Missing environment variable: BAIDU_SEARCH_API_KEY" in capsys.readouterr().out


def test_main_never_prints_the_key(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setenv("BAIDU_SEARCH_API_KEY", "top-secret-value")
    seen: list = []

    def send(url: str, headers: dict, payload: dict, timeout: float) -> Attempt:
        seen.append(headers.get("Authorization"))
        return ok(entry())

    monkeypatch.setattr(probe, "send_request", send)
    main(["--timeout", "5"])
    captured = capsys.readouterr()
    assert seen and all(value == "Bearer top-secret-value" for value in seen)
    assert "top-secret-value" not in captured.out
    assert "top-secret-value" not in captured.err