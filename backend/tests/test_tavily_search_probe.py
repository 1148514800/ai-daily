"""Tests for the Tavily Web Search probe.

The probe is allowed to call the real API exactly once, by hand, from
``python -m app.jobs.test_tavily_search``. The suite must not: every HTTP answer
here is injected, so running pytest never spends Tavily credits and never depends
on the network.

The autouse fixture below is the one that matters most. ``main()`` calls
``load_dotenv()``, and a developer who really has a ``TAVILY_API_KEY`` - in
``backend/.env`` or in the environment - would otherwise hand a live key to the
"no key configured" tests. That is exactly how the Baidu probe's suite broke
once, so the same guard is installed here from the start.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.jobs import test_tavily_search as probe
from app.jobs.test_aliyun_search import (
    OFFICIAL,
    PORTAL,
    PROFESSIONAL_MEDIA,
    RESEARCH,
    SECOND_HAND_DOMAINS,
    UGC_BLOG,
    UNKNOWN_QUALITY,
)
from app.jobs.test_tavily_search import (
    ENDPOINT,
    MAX_RESULTS_LIMIT,
    SEARCH_DEPTH,
    TIME_RANGE,
    TOPIC,
    Attempt,
    build_payload,
    describe_failure,
    error_message,
    find_result_list,
    format_tags,
    main,
    normalize_published,
    normalize_tags,
    parse_search_response,
    run,
    send_request,
    summarize,
    tag_of,
    to_search_result,
    usage_credits,
)
from app.jobs.test_baidu_search import (
    QUERY_POOL,
    is_within_last_24h,
    known_source_domains,
)

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)

# Tavily answers with RFC 2822 timestamps, not ISO ones.
INSIDE = "Sun, 20 Sep 2026 06:00:00 GMT"
OUTSIDE = "Fri, 18 Sep 2026 06:00:00 GMT"


@pytest.fixture(autouse=True)
def ignore_the_developers_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the probe's ``main()`` from reading the real ``backend/.env``."""
    monkeypatch.setattr(probe, "load_dotenv", lambda *args, **kwargs: None)


def item(**kwargs) -> dict:
    """One documented result entry."""
    node = {
        "title": "OpenAI ships a new model",
        "url": "https://openai.com/news/x",
        "content": "OpenAI shipped a new model today.",
        "score": 0.81,
        "published_date": INSIDE,
    }
    node.update(kwargs)
    return node


def body(*items, key: str = "results", **extra) -> dict:
    payload = {"query": "q", key: list(items)}
    payload.update(extra)
    return payload


def ok(*items, credits: int = 1) -> Attempt:
    payload = body(*items, usage={"credits": credits}, response_time=0.4)
    return Attempt(status_code=200, payload=payload, raw_text=json.dumps(payload))


def collect(attempt: Attempt, query: str = "q") -> list:
    parsed = parse_search_response(attempt.payload)
    known = known_source_domains()
    return [to_search_result(raw, query, known) for raw in parsed.results]


# --------------------------------------------------------------------------- #
# request
# --------------------------------------------------------------------------- #


def test_payload_matches_the_current_documented_search_shape() -> None:
    payload = build_payload("AI Agent 最新发布")
    assert payload["query"] == "AI Agent 最新发布"
    assert payload["topic"] == "news"
    assert payload["search_depth"] == "basic"
    assert payload["time_range"] == "day"
    assert payload["max_results"] == 10


def test_payload_uses_time_range_because_days_is_gone_from_the_reference() -> None:
    """``days`` no longer appears in Tavily's published API reference."""
    payload = build_payload("q")
    assert "days" not in payload
    assert payload["time_range"] == TIME_RANGE
    assert TIME_RANGE == "day"


def test_payload_never_enables_the_billed_content_options() -> None:
    payload = build_payload("q")
    assert payload["include_answer"] is False
    assert payload["include_raw_content"] is False
    assert payload["include_images"] is False


def test_payload_requests_the_published_date_the_recency_metric_needs() -> None:
    assert build_payload("q")["include_published_date"] is True


def test_payload_does_not_exclude_the_watched_domains() -> None:
    """Round one must measure raw recall, not the blacklist."""
    payload = build_payload("q")
    assert "exclude_domains" not in payload
    assert "include_domains" not in payload


def test_payload_asks_for_the_credit_count_so_the_run_is_verifiable() -> None:
    assert build_payload("q")["include_usage"] is True


def test_payload_carries_no_pinned_date() -> None:
    payload = json.dumps(build_payload("q"))
    assert "2026" not in payload
    assert "start_date" not in payload and "end_date" not in payload


def test_the_endpoint_is_the_official_tavily_search_api() -> None:
    assert ENDPOINT == "https://api.tavily.com/search"


def test_the_query_pool_is_the_same_one_the_other_probes_use() -> None:
    assert len(QUERY_POOL) == 10
    assert probe.QUERY_POOL is QUERY_POOL


# --------------------------------------------------------------------------- #
# response parsing
# --------------------------------------------------------------------------- #


def test_parses_a_normal_response() -> None:
    parsed = parse_search_response(ok(item()).payload)
    assert parsed.found is True
    assert parsed.list_key == "results"
    assert len(parsed.results) == 1
    raw = parsed.results[0]
    assert raw.title == "OpenAI ships a new model"
    assert raw.url == "https://openai.com/news/x"
    assert raw.score == "0.81"
    assert raw.published == INSIDE


def test_parses_multiple_results_in_order() -> None:
    payload = {
        "query": "q",
        "results": [
            {"title": "one", "url": "https://a.example.com/1"},
            {"title": "two", "url": "https://b.example.com/2"},
            {"title": "three", "url": "https://c.example.com/3"},
        ],
    }
    parsed = parse_search_response(payload)
    assert [raw.title for raw in parsed.results] == ["one", "two", "three"]


def test_empty_results_is_a_reading_success_with_no_results() -> None:
    parsed = parse_search_response({"query": "q", "results": []})
    assert parsed.found is True
    assert parsed.results == []
    assert parsed.skipped_no_url == 0


def test_a_response_without_results_is_reported_as_a_failure() -> None:
    parsed = parse_search_response({"query": "q", "answer": "hi"})
    assert parsed.found is False


def test_alternative_result_keys_are_accepted() -> None:
    for key in ("results", "data", "items", "documents"):
        parsed = parse_search_response({key: [item()]})
        assert parsed.found is True, key
        assert parsed.list_key == key


def test_an_entry_without_a_url_is_dropped_and_counted() -> None:
    parsed = parse_search_response(body({"title": "no url"}, item()))
    assert len(parsed.results) == 1
    assert parsed.skipped_no_url == 1


def test_a_non_object_entry_is_skipped_without_losing_the_response() -> None:
    parsed = parse_search_response({"results": ["https://example.com", item()]})
    assert len(parsed.results) == 1
    assert parsed.skipped_no_url == 1


def test_missing_fields_do_not_sink_the_response() -> None:
    payload = {"results": [{"url": "https://a.example.com/1"}]}
    parsed = parse_search_response(payload)
    assert len(parsed.results) == 1
    raw = parsed.results[0]
    assert raw.title == "" and raw.published == "" and raw.snippet == "" and raw.score == ""


def test_a_missing_score_is_reported_as_absent_not_zero() -> None:
    payload = {"results": [{"url": "https://a.example.com/1"}]}
    assert parse_search_response(payload).results[0].score == ""


def test_an_integer_score_is_kept_as_text() -> None:
    payload = {"results": [{"url": "https://a.example.com/1", "score": 1}]}
    assert parse_search_response(payload).results[0].score == "1"


def test_a_boolean_is_never_mistaken_for_a_url_or_a_score() -> None:
    payload = {"results": [{"url": "https://a.example.com/1", "score": True}]}
    assert parse_search_response(payload).results[0].score == ""


def test_a_nested_result_list_is_found() -> None:
    payload = {"data": {"results": [item()]}}
    parsed = parse_search_response(payload)
    found, path = find_result_list(payload)
    assert parsed.found is True
    assert len(found) == 1
    assert path == "data.results"


def test_the_credit_count_is_read_from_the_usage_block() -> None:
    assert parse_search_response(ok(credits=3).payload).credits == 3


def test_a_missing_usage_block_reports_zero_credits_not_a_guess() -> None:
    assert usage_credits({}) == 0
    assert usage_credits({"usage": {}}) == 0
    assert usage_credits({"usage": {"credits": "2"}}) == 0
    assert usage_credits({"usage": {"credits": True}}) == 0
    assert usage_credits("not a dict") == 0
    assert usage_credits({"usage": {"credits": 2}}) == 2

# --------------------------------------------------------------------------- #
# publish time: RFC 2822 in, the shared rule underneath
# --------------------------------------------------------------------------- #


def test_rfc_2822_is_normalised_so_the_shared_parser_can_read_it() -> None:
    assert normalize_published("Sun, 20 Sep 2026 14:00:00 GMT") == "2026-09-20T14:00:00+00:00"


def test_a_non_gmt_zone_is_kept_as_its_offset() -> None:
    moment = probe.parse_page_time(normalize_published("Sun, 20 Sep 2026 14:00:00 +0800"))
    assert moment.moment == datetime(2026, 9, 20, 14, 0, tzinfo=timezone(timedelta(hours=8)))
    assert moment.has_time is True


def test_tavily_style_dates_go_through_the_shared_parser_not_a_second_one() -> None:
    """The wire encoding is translated; which formats count stays one rule."""
    result = collect(ok(item(published_date=INSIDE)))
    assert result[0].page_time.moment == datetime(2026, 9, 20, 6, 0, tzinfo=timezone.utc)
    assert result[0].page_time.has_time is True


def test_a_null_published_date_is_unknown_not_an_invented_time() -> None:
    assert normalize_published(None) == ""
    assert normalize_published("") == ""
    assert normalize_published("   ") == ""
    result = collect(ok(item(published_date=None)))
    assert result[0].page_time.moment is None
    assert result[0].page_time.raw == ""


def test_an_unparseable_published_date_keeps_its_text() -> None:
    result = collect(ok(item(published_date="3 hours ago")))
    assert result[0].page_time.moment is None
    assert result[0].page_time.raw == "3 hours ago"


def test_iso_and_bare_dates_are_still_accepted_through_the_normaliser() -> None:
    assert normalize_published("2026-09-20") == "2026-09-20"
    assert normalize_published("2026-09-20T14:00:00+00:00") == "2026-09-20T14:00:00+00:00"


def test_a_bare_date_stays_date_only_and_is_not_counted_as_the_last_24h() -> None:
    summary = summarize([outcome("q1", item(published_date="2026-09-20"))], NOW)
    assert summary.published_known == 1
    assert summary.inside_24h == 0
    assert summary.unknown_publish == 1


def test_an_invalid_timestamp_does_not_sink_the_result() -> None:
    result = collect(ok(item(published_date="not a date at all")))
    assert len(result) == 1
    assert result[0].page_time.moment is None


# --------------------------------------------------------------------------- #
# tags
# --------------------------------------------------------------------------- #


def test_normalize_tags_flattens_values_to_text() -> None:
    assert normalize_tags({"genre": "Blog", "isUgc": "true"}) == {"genre": "Blog", "isUgc": "true"}
    assert normalize_tags({"genre": True}) == {"genre": "true"}


def test_normalize_tags_keeps_unknown_keys_and_drops_empties() -> None:
    assert normalize_tags({"genre": "Blog", "future": "kept", "empty": ""}) == {
        "genre": "Blog",
        "future": "kept",
    }


def test_normalize_tags_tolerates_a_non_map() -> None:
    assert normalize_tags(None) == {}
    assert normalize_tags(["genre"]) == {}
    assert normalize_tags("genre") == {}


def test_tag_lookup_is_case_insensitive() -> None:
    assert tag_of({"Genre": "Blog"}, "genre") == "Blog"


def test_format_tags_is_a_single_readable_line() -> None:
    assert format_tags({}) == "(none)"
    assert format_tags({"genre": "Blog"}) == "genre=Blog"


def test_genre_is_exposed_on_the_result_when_the_engine_sends_one() -> None:
    result = collect(ok(item(tags={"genre": "NewsPortal"})))
    assert result[0].genre == "NewsPortal"


def test_tavily_sends_no_tags_so_the_map_is_simply_empty() -> None:
    result = collect(ok(item()))
    assert result[0].tags == {}
    assert result[0].genre == ""


# --------------------------------------------------------------------------- #
# domains and quality buckets
# --------------------------------------------------------------------------- #


def test_the_domain_is_taken_from_the_url() -> None:
    result = collect(ok(item(url="https://www.36kr.com/p/123456")))
    assert result[0].domain == "36kr.com"


def test_a_configured_source_is_official() -> None:
    assert collect(ok(item(url="https://openai.com/news/x")))[0].quality == OFFICIAL


def test_an_unconfigured_first_party_vendor_is_not_official() -> None:
    """The buckets describe the engine; they never extend SOURCES."""
    assert collect(ok(item(url="https://brand-new-lab.example.com/p")))[0].quality == UNKNOWN_QUALITY


def test_portal_domains_are_portal() -> None:
    assert collect(ok(item(url="https://baijiahao.baidu.com/s?id=1")))[0].quality == PORTAL


def test_ugc_domains_are_ugc() -> None:
    assert collect(ok(item(url="https://zhuanlan.zhihu.com/p/1")))[0].quality == UGC_BLOG


def test_github_and_arxiv_are_research() -> None:
    assert collect(ok(item(url="https://github.com/x/y")))[0].quality == RESEARCH
    assert collect(ok(item(url="https://arxiv.org/abs/2609.1")))[0].quality == RESEARCH


def test_professional_media_is_its_own_bucket() -> None:
    assert collect(ok(item(url="https://www.bloomberg.com/news/x")))[0].quality == PROFESSIONAL_MEDIA


def test_domain_matching_respects_dot_boundaries() -> None:
    assert collect(ok(item(url="https://m.163.com/dy/article/x.html")))[0].quality == PORTAL
    assert collect(ok(item(url="https://not163.com/x")))[0].quality == UNKNOWN_QUALITY


def test_the_seven_watched_domains_are_all_recognised() -> None:
    known = known_source_domains()
    for domain in SECOND_HAND_DOMAINS:
        result = to_search_result(probe.RawResult(url=f"https://{domain}/p/1"), "q", known)
        assert probe.watched_domain_of(result.domain) == domain, domain


def test_a_subdomain_maps_back_to_its_watchlist_entry() -> None:
    known = known_source_domains()
    result = to_search_result(probe.RawResult(url="https://m.sohu.com/a/1"), "q", known)
    assert probe.watched_domain_of(result.domain) == "sohu.com"


def test_an_unwatched_domain_is_not_second_hand() -> None:
    assert probe.watched_domain_of("notsohu.com") == ""
    assert probe.watched_domain_of("") == ""


# --------------------------------------------------------------------------- #
# transport and failure reporting
# --------------------------------------------------------------------------- #


def test_send_request_never_raises_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    original = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    class Patched(original):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", Patched)
    attempt = send_request(ENDPOINT, {}, {"query": "x"}, 5.0)
    assert attempt.status_code is None
    assert "timed out" in attempt.transport_error
    assert "timed out" in describe_failure(attempt)


def test_send_request_never_raises_on_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*args, **kwargs):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(httpx, "Client", explode)
    attempt = send_request(ENDPOINT, {}, {"query": "x"}, 5.0)
    assert attempt.transport_error.startswith("connection failed")
    assert "connection failed" in describe_failure(attempt)


def fake_client(response) -> type:
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, *args, **kwargs):
            return response

    return FakeClient


def test_send_request_reports_a_non_json_body(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        status_code = 200
        text = "<html>gateway</html>"

        def json(self):
            raise ValueError("no json here")

    monkeypatch.setattr(httpx, "Client", fake_client(Response()))
    attempt = send_request(ENDPOINT, {}, {"query": "x"}, 5.0)
    assert attempt.status_code == 200
    assert attempt.parsed is False
    assert "not JSON" in describe_failure(attempt)


def test_401_is_reported_as_a_rejected_key_with_the_verified_error_shape() -> None:
    """Verified live: an invalid key answers 401 with detail.error."""
    payload = {"detail": {"error": "Unauthorized: missing or invalid API key."}}
    attempt = Attempt(status_code=401, payload=payload, raw_text=json.dumps(payload))
    message = describe_failure(attempt)
    assert "API key was rejected" in message
    assert "missing or invalid API key" in message


def test_403_is_reported_as_a_rejected_key() -> None:
    attempt = Attempt(status_code=403, payload={"detail": {"error": "Forbidden"}})
    assert "API key was rejected" in describe_failure(attempt)


def test_429_is_reported_without_retrying() -> None:
    attempt = Attempt(status_code=429, payload={"detail": {"error": "too many requests"}})
    message = describe_failure(attempt)
    assert "rate limited" in message
    assert "does not retry" in message


def test_400_is_reported_with_the_service_message() -> None:
    """Verified live: an invalid topic answers 400 with detail.error."""
    payload = {"detail": {"error": "Invalid topic. Must be 'general', 'news', or 'finance'"}}
    attempt = Attempt(status_code=400, payload=payload)
    message = describe_failure(attempt)
    assert "HTTP 400" in message
    assert "Invalid topic" in message


def test_422_is_reported_as_a_rejected_request() -> None:
    attempt = Attempt(status_code=422, payload={"detail": "bad"})
    assert "HTTP 422" in describe_failure(attempt)


@pytest.mark.parametrize("status", [500, 502, 503])
def test_5xx_is_reported_as_a_tavily_failure(status: int) -> None:
    attempt = Attempt(status_code=status, payload={"detail": {"error": "internal"}})
    message = describe_failure(attempt)
    assert f"HTTP {status}" in message
    assert "Tavily failed" in message


def test_a_plan_limit_is_reported_as_such() -> None:
    attempt = Attempt(status_code=432, payload={"detail": {"error": "plan usage limit"}})
    assert "usage limit" in describe_failure(attempt)


def test_a_200_without_results_names_the_schema_that_came_back() -> None:
    payload = {"query": "q", "answer": None, "images": []}
    attempt = Attempt(status_code=200, payload=payload, raw_text=json.dumps(payload))
    message = describe_failure(attempt)
    assert "no results list" in message
    assert "query" in message and "images" in message


def test_error_message_reads_the_documented_error_shape() -> None:
    assert error_message({"detail": {"error": "bad key"}}) == "bad key"
    assert error_message({"detail": "plain"}) == "plain"
    assert error_message({"message": "oops"}) == "oops"
    assert error_message("not a dict") == ""
    assert error_message({}) == ""


def test_error_message_reads_the_422_validation_shape() -> None:
    payload = {"detail": [{"type": "missing", "loc": ["body", "query"], "msg": "Field required"}]}
    message = error_message(payload)
    assert "query" in message
    assert "Field required" in message

# --------------------------------------------------------------------------- #
# dedupe and statistics
# --------------------------------------------------------------------------- #


def outcome(query: str, *items) -> probe.QueryOutcome:
    attempt = ok(*items)
    result = probe.QueryOutcome(query=query, attempt=attempt)
    parsed = parse_search_response(attempt.payload)
    known = known_source_domains()
    result.results = [to_search_result(raw, query, known) for raw in parsed.results]
    result.credits = parsed.credits
    return result


def test_the_same_url_from_two_queries_is_counted_once() -> None:
    shared = item(url="https://example.com/story")
    summary = summarize([outcome("q1", shared), outcome("q2", shared)], NOW)
    assert summary.raw_results == 2
    assert summary.unique_urls == 1
    assert summary.duplicates == 1


def test_tracking_parameters_do_not_create_a_second_result() -> None:
    summary = summarize(
        [
            outcome("q1", item(url="https://example.com/story")),
            outcome("q2", item(url="https://example.com/story?utm_source=x&utm_medium=y")),
        ],
        NOW,
    )
    assert summary.unique_urls == 1
    assert summary.duplicates == 1


def test_summary_counts_known_and_discovered_hostnames() -> None:
    summary = summarize(
        [outcome("q1", item(url="https://openai.com/news/x"), item(url="https://newlab.example.com/p"))],
        NOW,
    )
    assert summary.known_sources == 1
    assert summary.discovered == 1


def test_summary_counts_recency_buckets() -> None:
    summary = summarize(
        [
            outcome(
                "q1",
                item(url="https://a.example.com/1", published_date=INSIDE),
                item(url="https://b.example.com/2", published_date=OUTSIDE),
                item(url="https://c.example.com/3", published_date=None),
            )
        ],
        NOW,
    )
    assert summary.published_known == 2
    assert summary.inside_24h == 1
    assert summary.outside_24h == 1
    assert summary.unknown_publish == 1


def test_exact_last_24h_boundary_is_inclusive_but_older_is_not() -> None:
    """``time_range=day`` is a request, not a guarantee: this is the local check."""
    exactly_24h = "Sun, 19 Sep 2026 12:00:00 GMT"
    one_second_older = "Sun, 19 Sep 2026 11:59:59 GMT"
    summary = summarize(
        [
            outcome(
                "q1",
                item(url="https://a.example.com/1", published_date=exactly_24h),
                item(url="https://b.example.com/2", published_date=one_second_older),
            )
        ],
        NOW,
    )
    assert summary.inside_24h == 1
    assert summary.outside_24h == 1
    assert is_within_last_24h(datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc), NOW) is True
    assert is_within_last_24h(datetime(2026, 9, 19, 11, 59, 59, tzinfo=timezone.utc), NOW) is False


def test_a_future_timestamp_is_never_inside_the_last_24h() -> None:
    summary = summarize([outcome("q1", item(published_date="Wed, 30 Sep 2026 00:00:00 GMT"))], NOW)
    assert summary.inside_24h == 0
    assert summary.outside_24h == 1


def test_summary_counts_quality_buckets_and_the_watchlist() -> None:
    summary = summarize(
        [
            outcome(
                "q1",
                item(url="https://baijiahao.baidu.com/s?id=1"),
                item(url="https://zhuanlan.zhihu.com/p/1"),
                item(url="https://github.com/x/y"),
                item(url="https://openai.com/news/x"),
            )
        ],
        NOW,
    )
    assert summary.quality[PORTAL] == 1
    assert summary.quality[UGC_BLOG] == 1
    assert summary.quality[RESEARCH] == 1
    assert summary.quality[OFFICIAL] == 1
    assert summary.second_hand == 2


def test_watchlist_aggregates_subdomains_under_the_watchlist_entry() -> None:
    summary = summarize(
        [
            outcome(
                "q1",
                item(url="https://baijiahao.baidu.com/s?id=1"),
                item(url="https://baijiahao.baidu.com/s?id=2"),
                item(url="https://m.163.com/dy/article/x.html"),
                item(url="https://www.163.com/dy/article/y.html"),
                item(url="https://m.sohu.com/a/1"),
            )
        ],
        NOW,
    )
    assert summary.watched["baijiahao.baidu.com"] == 2
    assert summary.watched["163.com"] == 2
    assert summary.watched["sohu.com"] == 1
    assert summary.second_hand == 5


def test_no_watched_domain_appearing_reports_zero() -> None:
    summary = summarize([outcome("q1", item(url="https://openai.com/news/x"))], NOW)
    assert summary.watched == {}
    assert summary.second_hand == 0


def test_failed_and_skipped_queries_are_counted_separately() -> None:
    failed = probe.QueryOutcome(query="q2", attempt=Attempt(status_code=500, payload={"detail": "x"}))
    failed.error = describe_failure(failed.attempt)
    skipped = probe.QueryOutcome(query="q3", skipped="too long")
    summary = summarize([outcome("q1", item()), failed, skipped], NOW)
    assert summary.queries == 3
    assert summary.successful == 1
    assert summary.failed == 1
    assert summary.skipped == 1


def test_a_failed_query_contributes_no_credits() -> None:
    failed = probe.QueryOutcome(query="q2", attempt=Attempt(status_code=500, payload={}), error="boom")
    summary = summarize([outcome("q1", item()), failed], NOW)
    assert summary.credits == 1


def test_credits_are_summed_across_successful_queries() -> None:
    summary = summarize([outcome("q1", item()), outcome("q2", item(url="https://b.example.com/2"))], NOW)
    assert summary.credits == 2


def test_the_summary_records_what_was_requested() -> None:
    summary = summarize([outcome("q1", item())], NOW)
    assert summary.topic == TOPIC
    assert summary.search_depth == SEARCH_DEPTH
    assert summary.time_range == TIME_RANGE


def test_only_the_watched_and_unknown_results_are_kept_in_the_irrelevant_list() -> None:
    summary = summarize(
        [outcome("q1", item(url="https://a.example.com/1", title="Gardening tips", content="soil"))],
        NOW,
    )
    assert len(summary.irrelevant) == 1
    assert summary.irrelevant[0].domain == "a.example.com"


def test_the_domain_counter_counts_each_unique_url_once_per_domain() -> None:
    summary = summarize(
        [
            outcome(
                "q1",
                item(url="https://www.163.com/a"),
                item(url="https://www.163.com/b"),
                item(url="https://openai.com/c"),
            )
        ],
        NOW,
    )
    assert summary.domains["163.com"] == 2
    assert summary.unique_domains == 2

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
        query = payload["query"]
        if calls is not None:
            calls.append({"url": url, "headers": headers, "payload": payload, "timeout": timeout})
        return responses[query]

    return send


def all_ok(calls: list | None = None):
    return fake_send(
        {query: ok(item(url=f"https://example.com/{index}")) for index, query in enumerate(QUERY_POOL)},
        calls,
    )


def test_run_sends_one_request_per_query_to_the_documented_endpoint() -> None:
    calls: list = []
    status = run(api_key="secret", queries=QUERY_POOL, now=NOW, send=all_ok(calls), out=Recorder())
    assert status == 0
    assert len(calls) == len(QUERY_POOL)
    assert all(call["url"] == ENDPOINT for call in calls)
    assert all(call["headers"]["Authorization"] == "Bearer secret" for call in calls)
    assert all(call["payload"]["topic"] == TOPIC for call in calls)
    assert all(call["payload"]["search_depth"] == SEARCH_DEPTH for call in calls)
    assert all(call["payload"]["time_range"] == TIME_RANGE for call in calls)


def test_run_never_sends_the_watchlist_as_an_exclusion() -> None:
    calls: list = []
    run(api_key="secret", queries=QUERY_POOL, now=NOW, send=all_ok(calls), out=Recorder())
    for call in calls:
        assert "exclude_domains" not in call["payload"]
        assert all(domain not in json.dumps(call["payload"]) for domain in SECOND_HAND_DOMAINS)


def test_run_keeps_going_after_one_query_fails() -> None:
    responses = {query: ok(item(url=f"https://example.com/{index}")) for index, query in enumerate(QUERY_POOL)}
    responses["AI Agent 最新发布"] = Attempt(status_code=500, payload={"detail": {"error": "boom"}})
    calls: list = []
    status = run(api_key="secret", queries=QUERY_POOL, now=NOW, send=fake_send(responses, calls), out=Recorder())
    assert len(calls) == len(QUERY_POOL)
    assert status == 0


def test_query_failure_isolation_keeps_the_remaining_queries_intact() -> None:
    """A failure in the middle must not remove the queries after it."""
    responses = {query: ok(item(url=f"https://example.com/{index}")) for index, query in enumerate(QUERY_POOL)}
    failed = QUERY_POOL[3]
    responses[failed] = Attempt(status_code=429, payload={"detail": {"error": "slow down"}})
    calls: list = []
    recorder = Recorder()
    run(api_key="secret", queries=QUERY_POOL, now=NOW, send=fake_send(responses, calls), out=recorder)
    assert len(calls) == len(QUERY_POOL)
    assert recorder.text.count("QUERY:") == len(QUERY_POOL)
    assert f"QUERY: {failed}" in recorder.text
    assert "Successful: 9" in recorder.text


def test_a_429_does_not_abort_or_retry_the_run() -> None:
    """One 429 must not cost the other nine queries, and must not be retried."""
    calls: list = []
    responses = {query: ok(item(url=f"https://example.com/{index}")) for index, query in enumerate(QUERY_POOL)}
    responses[QUERY_POOL[0]] = Attempt(status_code=429, payload={"detail": {"error": "slow down"}})
    recorder = Recorder()
    status = run(api_key="secret", queries=QUERY_POOL, now=NOW, send=fake_send(responses, calls), out=recorder)
    assert len(calls) == len(QUERY_POOL)
    assert status == 0
    assert "Successful: 9" in recorder.text
    assert "Failed: 1" in recorder.text


def test_run_reports_failed_and_successful_queries() -> None:
    responses = {"good": ok(item()), "bad": Attempt(status_code=429, payload={"detail": {"error": "slow"}})}
    recorder = Recorder()
    run(api_key="secret", queries=("good", "bad"), now=NOW, send=fake_send(responses), out=recorder)
    assert "Successful: 1" in recorder.text
    assert "Failed: 1" in recorder.text
    assert "QUERY: bad" in recorder.text


def test_each_query_is_printed_exactly_once() -> None:
    recorder = Recorder()
    run(
        api_key="secret",
        queries=("q1", "q2"),
        now=NOW,
        send=fake_send({"q1": ok(item(url="https://example.com/1")), "q2": ok(item(url="https://example.com/2"))}),
        out=recorder,
    )
    assert recorder.text.count("QUERY: q1") == 1
    assert recorder.text.count("QUERY: q2") == 1
    assert recorder.text.count("SUMMARY") == 1


def test_run_never_sends_an_over_long_query() -> None:
    calls: list = []
    recorder = Recorder()
    run(api_key="secret", queries=("AI " * 60,), now=NOW, send=fake_send({}, calls), out=recorder)
    assert calls == []
    assert "SKIPPED" in recorder.text


def test_run_prints_the_required_header_without_the_key() -> None:
    recorder = Recorder()
    run(api_key="super-secret-key", queries=("q",), now=NOW, send=fake_send({"q": ok(item())}), out=recorder)
    assert "Tavily Web Search Probe" in recorder.text
    assert f"Endpoint: {ENDPOINT}" in recorder.text
    assert "API key: configured" in recorder.text
    assert "super-secret-key" not in recorder.text


def test_run_prints_the_required_summary_shape() -> None:
    recorder = Recorder()
    run(
        api_key="secret",
        queries=("q1", "q2"),
        now=NOW,
        send=fake_send(
            {
                "q1": ok(item(url="https://openai.com/news/x")),
                "q2": ok(item(url="https://newlab.example.com/p")),
            }
        ),
        out=recorder,
    )
    for expected in (
        "SUMMARY",
        "Provider: Tavily",
        f"Topic: {TOPIC}",
        "Days: 1",
        f"Search depth: {SEARCH_DEPTH}",
        "Queries: 2",
        "Successful: 2",
        "Failed: 0",
        "Raw results: 2",
        "Unique URLs: 2",
        "Duplicate URLs: 0",
        "Published time available: 2",
        "Inside last 24h: 2",
        "Outside last 24h: 0",
        "Unknown publish time: 0",
        "Unique domains: 2",
        "Known fixed-source URLs: 1",
        "New/discovered URLs: 1",
        "Top domains:",
        "SOURCE QUALITY (probe analysis only)",
        "Official/company domains",
        "Professional media",
        "GitHub/arXiv",
        "Portal/repost",
        "UGC/blog",
        "Unknown",
        "TOTAL",
        "Second-hand / UGC watchlist",
        "Credits reported by the API: 2",
    ):
        assert expected in recorder.text, expected


def test_run_prints_the_watchlist_names_only_when_they_appeared() -> None:
    recorder = Recorder()
    run(
        api_key="secret",
        queries=("q",),
        now=NOW,
        send=fake_send(
            {
                "q": ok(
                    item(url="https://baijiahao.baidu.com/s?id=1"),
                    item(url="https://blog.csdn.net/a/article/details/1"),
                )
            }
        ),
        out=recorder,
    )
    assert "Second-hand / UGC watchlist" in recorder.text
    assert "baijiahao.baidu.com" in recorder.text
    assert "blog.csdn.net" in recorder.text
    assert "Results carrying tags: 0 of 2" in recorder.text


def test_run_prints_the_top_ten_discovered_with_the_required_fields() -> None:
    items = [
        item(
            title=f"Fresh discovery {index}",
            url=f"https://newlab{index}.example.com/post",
            score=0.5 + index / 100,
        )
        for index in range(12)
    ]
    recorder = Recorder()
    run(api_key="secret", queries=("q",), now=NOW, send=fake_send({"q": ok(*items)}), out=recorder)
    assert "TOP 10 VALUABLE DISCOVERED RESULTS" in recorder.text
    assert "newlab0.example.com" in recorder.text
    for field in ("domain:", "published_at:", "score:", "tags:", "url:"):
        assert field in recorder.text, field
    # Twelve discovered results, but only the ten most valuable are listed.
    assert "11. Fresh discovery" not in recorder.text


def test_the_discovered_list_is_sorted_by_recency_then_score() -> None:
    recorder = Recorder()
    run(
        api_key="secret",
        queries=("q",),
        now=NOW,
        send=fake_send(
            {
                "q": ok(
                    item(title="older", url="https://a.example.com/1", published_date=OUTSIDE, score=0.99),
                    item(title="recent-low-score", url="https://b.example.com/2", score=0.10),
                    item(title="recent-high-score", url="https://c.example.com/3", score=0.90),
                )
            }
        ),
        out=recorder,
    )
    # Slice out the discovered section: the per-query output above it keeps the
    # API's own order, which is exactly what this ordering must not be confused with.
    discovered = recorder.text.split("TOP 10 VALUABLE DISCOVERED RESULTS", 1)[1]
    assert discovered.index("recent-high-score") < discovered.index("recent-low-score")
    assert discovered.index("recent-low-score") < discovered.index("older")


def test_the_discovered_list_excludes_configured_sources() -> None:
    recorder = Recorder()
    run(
        api_key="secret",
        queries=("q",),
        now=NOW,
        send=fake_send({"q": ok(item(url="https://openai.com/news/x"))}),
        out=recorder,
    )
    assert "every hostname Tavily returned is already a configured source" in recorder.text


def test_run_prints_no_result_as_an_empty_list_not_an_error() -> None:
    recorder = Recorder()
    status = run(api_key="secret", queries=("q",), now=NOW, send=fake_send({"q": ok()}), out=recorder)
    assert status == 0
    assert "Results: 0" in recorder.text
    assert "(no results to compare)" in recorder.text


def test_run_counts_results_dropped_for_having_no_url() -> None:
    recorder = Recorder()
    run(api_key="secret", queries=("q",), now=NOW, send=fake_send({"q": ok({"title": "no url"}, item())}), out=recorder)
    assert "1 without a URL, skipped" in recorder.text


def test_run_exits_unusable_when_no_query_succeeds() -> None:
    recorder = Recorder()
    attempt = Attempt(status_code=401, payload={"detail": {"error": "bad key"}})
    status = run(
        api_key="bad",
        queries=("q1", "q2"),
        now=NOW,
        send=fake_send({"q1": attempt, "q2": attempt}),
        out=recorder,
    )
    assert status == 1
    assert "Successful: 0" in recorder.text
    assert "Failed: 2" in recorder.text


def test_run_does_not_touch_the_source_configuration() -> None:
    """The quality buckets are probe-local: SOURCES must be unchanged after a run."""
    from app.config.sources import SOURCES

    before = tuple(SOURCES)
    run(api_key="secret", queries=("q",), now=NOW, send=fake_send({"q": ok(item())}), out=Recorder())
    assert tuple(SOURCES) == before


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #


def test_main_without_a_key_reports_the_missing_variable_and_exits_cleanly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    status = main([])
    captured = capsys.readouterr()
    assert status == 2
    assert "Missing environment variable: TAVILY_API_KEY" in captured.out
    assert "Traceback" not in captured.out
    assert "Traceback" not in captured.err


def test_main_does_not_call_the_api_when_the_key_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("the probe must not send a request without a key")

    monkeypatch.setattr(probe, "send_request", forbidden)
    assert main([]) == 2


def test_a_blank_key_counts_as_missing(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "   ")
    assert main([]) == 2
    assert "Missing environment variable: TAVILY_API_KEY" in capsys.readouterr().out


def test_main_never_prints_the_key(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-top-secret-value")
    seen: list = []

    def send(url: str, headers: dict, payload: dict, timeout: float) -> Attempt:
        seen.append(headers.get("Authorization"))
        return ok(item())

    monkeypatch.setattr(probe, "send_request", send)
    main(["--timeout", "5"])
    captured = capsys.readouterr()
    assert seen and all(value == "Bearer tvly-top-secret-value" for value in seen)
    assert "tvly-top-secret-value" not in captured.out
    assert "tvly-top-secret-value" not in captured.err


def test_main_uses_the_bearer_scheme_the_reference_documents(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "secret")
    headers_seen: list = []

    def send(url: str, headers: dict, payload: dict, timeout: float) -> Attempt:
        headers_seen.append(headers)
        return ok(item())

    monkeypatch.setattr(probe, "send_request", send)
    main([])
    assert headers_seen
    assert all(h["Authorization"].startswith("Bearer ") for h in headers_seen)
    assert all(h["Content-Type"] == "application/json" for h in headers_seen)


def test_main_defaults_to_news_basic_and_day(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "secret")
    payloads: list = []

    def send(url: str, headers: dict, payload: dict, timeout: float) -> Attempt:
        payloads.append(payload)
        return ok(item())

    monkeypatch.setattr(probe, "send_request", send)
    main([])
    assert payloads
    assert {p["topic"] for p in payloads} == {TOPIC}
    assert {p["search_depth"] for p in payloads} == {SEARCH_DEPTH}
    assert {p["time_range"] for p in payloads} == {TIME_RANGE}


def test_main_refuses_an_over_limit_max_results_without_sending(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "secret")

    def forbidden(*args, **kwargs):
        raise AssertionError("an over-limit request must not be sent")

    monkeypatch.setattr(probe, "send_request", forbidden)
    assert main(["--max-results", str(MAX_RESULTS_LIMIT + 1)]) == 2
    assert "Nothing was sent" in capsys.readouterr().out


def test_the_suite_neutralises_load_dotenv_so_no_real_key_can_leak_in() -> None:
    """The guard the Baidu suite had to add after a real key broke it.

    ``main()`` calls ``load_dotenv()``, which fills in any variable the process
    does not already have. Without the autouse fixture a developer's real
    ``TAVILY_API_KEY`` would reach the "no key configured" tests, and the suite
    would spend live credits. ``load_dotenv`` is patched to a no-op, so this
    asserts the patch is actually installed rather than merely present in a file.
    """
    from app.config.env import load_dotenv as real_load_dotenv

    assert probe.load_dotenv is not real_load_dotenv
    assert probe.load_dotenv("backend/.env") is None