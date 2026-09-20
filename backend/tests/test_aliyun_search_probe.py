"""Tests for the Aliyun CleverSee Web Search probe.

The probe is allowed to call the real API exactly once, by hand, from
``python -m app.jobs.test_aliyun_search``. The suite must not: every HTTP answer
here is injected, so running pytest never spends CleverSee quota and never depends
on the network.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.jobs import test_aliyun_search as probe
from app.jobs.test_aliyun_search import (
    ENDPOINT,
    ENGINE_TYPE,
    UGC_BLOG,
    UNKNOWN_QUALITY,
    OFFICIAL,
    PORTAL,
    PROFESSIONAL_MEDIA,
    RESEARCH,
    SECOND_HAND_DOMAINS,
    Attempt,
    build_payload,
    classify_source,
    describe_failure,
    error_message,
    find_page_items,
    format_tags,
    is_second_hand_domain,
    is_ugc,
    main,
    normalize_tags,
    parse_search_response,
    run,
    send_request,
    summarize,
    tag_of,
    to_search_result,
)
from app.jobs.test_baidu_search import (
    QUERY_POOL,
    is_within_last_24h,
    known_source_domains,
    probe_date_range,
)

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def ignore_the_developers_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the probe's ``main()`` from reading the real ``backend/.env``.

    Same reason as the Baidu probe's fixture: ``main()`` calls ``load_dotenv()``,
    which would hand a developer's real key to the "no key configured" tests.
    """
    monkeypatch.setattr(probe, "load_dotenv", lambda *args, **kwargs: None)
INSIDE = "2026-09-20T06:00:00+08:00"
OUTSIDE = "2026-09-18T06:00:00+08:00"


def item(**kwargs) -> dict:
    """One documented pageItems entry."""
    node = {
        "title": "阿里云发布新模型",
        "link": "https://www.aliyun.com/news/x",
        "hostname": "阿里云",
        "publishedTime": INSIDE,
        "snippet": "阿里云发布了新模型。",
        "rerankScore": 0.91,
        "tags": {"genre": "NewsPortal", "isUgc": "false", "industry": "Tech", "isListPage": "false"},
    }
    node.update(kwargs)
    return node


def body(*items, key: str = "pageItems", **extra) -> dict:
    payload = {"requestId": "abc", key: list(items)}
    payload.update(extra)
    return payload


def ok(*items) -> Attempt:
    payload = body(*items)
    return Attempt(status_code=200, payload=payload, raw_text=json.dumps(payload))


def collect(attempt: Attempt, query: str = "q") -> list:
    parsed = parse_search_response(attempt.payload)
    known = known_source_domains()
    return [to_search_result(raw, query, known) for raw in parsed.results]


# --------------------------------------------------------------------------- #
# request
# --------------------------------------------------------------------------- #


def test_payload_matches_the_documented_unified_search_shape() -> None:
    payload = build_payload("AI Agent 最新发布", "2026-09-19", "2026-09-20")
    assert payload["query"] == "AI Agent 最新发布"
    assert payload["engineType"] == "CNLiteBasic"
    assert payload["contents"] == {
        "mainText": False,
        "markdownText": False,
        "summary": False,
        "rerankScore": True,
    }


def test_payload_sends_num_results_as_a_string() -> None:
    """advancedParams is typed map<string, string> in the reference."""
    payload = build_payload("q", "2026-09-19", "2026-09-20")
    assert payload["advancedParams"]["numResults"] == "10"
    assert isinstance(payload["advancedParams"]["numResults"], str)


def test_payload_carries_the_shared_date_range() -> None:
    payload = build_payload("q", "2026-09-19", "2026-09-20")
    assert payload["advancedParams"]["startPublishedDate"] == "2026-09-19"
    assert payload["advancedParams"]["endPublishedDate"] == "2026-09-20"


def test_payload_never_asks_for_the_ai_summary() -> None:
    contents = build_payload("q", "2026-09-19", "2026-09-20")["contents"]
    assert contents["summary"] is False
    assert contents["mainText"] is False
    assert contents["markdownText"] is False


def test_payload_does_not_exclude_the_watched_domains() -> None:
    """Round one must show raw recall, so excludeSites must stay absent."""
    advanced = build_payload("q", "2026-09-19", "2026-09-20")["advancedParams"]
    assert "excludeSites" not in advanced
    assert "includeSites" not in advanced


def test_the_engine_is_cn_lite_basic_only() -> None:
    assert ENGINE_TYPE == "CNLiteBasic"
    assert build_payload("q", "2026-09-19", "2026-09-20")["engineType"] == ENGINE_TYPE


def test_endpoint_is_the_cleversee_unified_search_api() -> None:
    assert ENDPOINT == "https://cloud-iqs.aliyuncs.com/search/unified"
    assert ENDPOINT.startswith("https://")


def test_the_query_pool_is_the_same_one_the_baidu_probe_uses() -> None:
    """Identical queries are what makes the two engines comparable."""
    from app.jobs import test_baidu_search

    assert probe.QUERY_POOL is test_baidu_search.QUERY_POOL
    assert len(QUERY_POOL) == 10


def test_the_date_range_is_shared_with_the_baidu_probe() -> None:
    assert probe.probe_date_range is probe.probe_date_range
    assert probe_date_range(NOW) == ("2026-09-19", "2026-09-20")


# --------------------------------------------------------------------------- #
# parsing
# --------------------------------------------------------------------------- #


def test_parses_a_normal_response() -> None:
    parsed = parse_search_response(body(item()))
    assert parsed.found
    assert parsed.list_key == "pageItems"
    assert len(parsed.results) == 1
    result = parsed.results[0]
    assert result.title == "阿里云发布新模型"
    assert result.url == "https://www.aliyun.com/news/x"
    assert result.published == INSIDE
    assert result.rerank_score == "0.91"
    assert result.tags["genre"] == "NewsPortal"


def test_parses_multiple_results_in_order() -> None:
    payload = body(
        item(title="first", link="https://a.example.com/1"),
        item(title="second", link="https://b.example.com/2"),
        item(title="third", link="https://c.example.com/3"),
    )
    assert [r.title for r in parse_search_response(payload).results] == ["first", "second", "third"]


def test_empty_result_list_is_a_reading_success_with_no_results() -> None:
    parsed = parse_search_response(body())
    assert parsed.found is True
    assert parsed.results == []


def test_a_response_without_page_items_is_reported_as_a_failure() -> None:
    parsed = parse_search_response({"requestId": "abc", "searchInformation": {"searchTime": 100}})
    assert parsed.found is False


def test_alternative_item_keys_are_accepted() -> None:
    for key in ("items", "results", "documents", "data"):
        parsed = parse_search_response({key: [item()]})
        assert parsed.found, key
        assert parsed.list_key == key


def test_an_entry_without_a_url_is_dropped_and_counted() -> None:
    parsed = parse_search_response(body(item(link=""), item(link="")))
    assert parsed.results == []
    assert parsed.skipped_no_url == 2


def test_a_non_object_entry_is_skipped_without_losing_the_response() -> None:
    parsed = parse_search_response({"pageItems": [item(), "not a result", 42]})
    assert len(parsed.results) == 1


def test_missing_fields_do_not_sink_the_response() -> None:
    payload = body({"link": "https://example.com/only-url"})
    parsed = parse_search_response(payload)
    assert len(parsed.results) == 1
    result = parsed.results[0]
    assert result.title == ""
    assert result.snippet == ""
    assert result.published == ""
    assert result.rerank_score == ""
    assert result.tags == {}


def test_a_missing_rerank_score_is_reported_as_absent_not_zero() -> None:
    """CNLiteBasic always returns a score, but a rename must not look like 0.0."""
    result = collect(ok(item(rerankScore=None)))[0]
    assert result.rerank_score == ""


def test_item_list_nested_under_another_key_is_found() -> None:
    nodes, key = find_page_items({"data": {"pageItems": [item()]}})
    assert nodes is not None
    assert key == "data.pageItems"


# --------------------------------------------------------------------------- #
# tags
# --------------------------------------------------------------------------- #


def test_normalize_tags_flattens_values_to_text() -> None:
    tags = normalize_tags({"genre": "Blog", "isUgc": True, "isListPage": False, "score": 3})
    assert tags == {"genre": "Blog", "isUgc": "true", "isListPage": "false", "score": "3"}


def test_normalize_tags_keeps_unknown_keys_and_drops_empties() -> None:
    tags = normalize_tags({"genre": "Blog", "brandNewTag": "x", "empty": "", "none": None})
    assert tags == {"genre": "Blog", "brandNewTag": "x"}


def test_normalize_tags_tolerates_a_non_map() -> None:
    assert normalize_tags(None) == {}
    assert normalize_tags("genre=Blog") == {}
    assert normalize_tags([]) == {}


def test_tag_lookup_is_case_insensitive() -> None:
    assert tag_of({"Genre": "Official"}, "genre") == "Official"
    assert tag_of({}, "genre") == ""


def test_is_ugc_reads_the_documented_string_boolean() -> None:
    assert is_ugc({"isUgc": "true"}) is True
    assert is_ugc({"isUgc": "false"}) is False
    assert is_ugc({"isUgc": "True"}) is True


def test_is_ugc_absent_or_unknown_is_false_not_a_guess() -> None:
    assert is_ugc({}) is False
    assert is_ugc({"isUgc": "maybe"}) is False


def test_format_tags_is_a_single_readable_line() -> None:
    assert format_tags({"genre": "Blog", "isUgc": "true"}) == "genre=Blog isUgc=true"
    assert format_tags({}) == "(none)"


def test_genre_is_exposed_on_the_result() -> None:
    result = collect(ok(item(tags={"genre": "ForumUgc"})))[0]
    assert result.genre == "ForumUgc"


# --------------------------------------------------------------------------- #
# source quality
# --------------------------------------------------------------------------- #


def test_a_configured_source_is_official() -> None:
    known = known_source_domains()
    assert classify_source("openai.com", known=known) == OFFICIAL
    assert classify_source("techcrunch.com", known=known) == OFFICIAL


def test_an_unconfigured_first_party_vendor_is_not_official() -> None:
    """The bucket follows SOURCES, so a vendor the project does not read falls
    through to unknown - which is exactly what "discovered" means here."""
    assert classify_source("someplatform.ai") == UNKNOWN_QUALITY


def test_portal_domains_are_portal() -> None:
    for domain in ("baijiahao.baidu.com", "www.163.com", "m.163.com", "sohu.com", "sina.com.cn"):
        assert classify_source(domain) == PORTAL, domain


def test_ugc_domains_are_ugc() -> None:
    for domain in ("zhuanlan.zhihu.com", "blog.csdn.net", "weibo.com", "xueqiu.com"):
        assert classify_source(domain) == UGC_BLOG, domain


def test_github_and_arxiv_are_research() -> None:
    assert classify_source("github.com") == RESEARCH
    assert classify_source("arxiv.org") == RESEARCH


def test_professional_media_is_its_own_bucket() -> None:
    assert classify_source("www.bloomberg.com") == PROFESSIONAL_MEDIA


def test_a_ugc_tag_is_used_only_after_the_domain_lists() -> None:
    """The reference warns tags are incomplete, so domain evidence wins."""
    assert classify_source("someblog.dev", tags={"isUgc": "true"}) == UGC_BLOG
    assert classify_source("www.163.com", tags={"isUgc": "false"}) == PORTAL


def test_domain_matching_respects_dot_boundaries() -> None:
    assert classify_source("not163.com") == UNKNOWN_QUALITY
    assert classify_source("163.com.evil.example") == UNKNOWN_QUALITY
    assert classify_source("") == UNKNOWN_QUALITY


def test_the_seven_watched_domains_are_all_recognised() -> None:
    assert len(SECOND_HAND_DOMAINS) == 7
    for domain in SECOND_HAND_DOMAINS:
        assert is_second_hand_domain(domain), domain


def test_watched_matching_also_covers_subdomains() -> None:
    assert is_second_hand_domain("m.sohu.com")
    assert is_second_hand_domain("epaper.163.com")


def test_a_subdomain_maps_back_to_its_watchlist_entry() -> None:
    assert probe.watched_domain_of("m.163.com") == "163.com"
    assert probe.watched_domain_of("zhuanlan.zhihu.com") == "zhuanlan.zhihu.com"
    assert probe.watched_domain_of("baijiahao.baidu.com") == "baijiahao.baidu.com"
    assert probe.watched_domain_of("openai.com") == ""
    assert probe.watched_domain_of("") == ""


def test_an_unwatched_domain_is_not_second_hand() -> None:
    assert not is_second_hand_domain("openai.com")
    assert not is_second_hand_domain("github.com")
    assert not is_second_hand_domain("")
    assert not is_second_hand_domain("notsohu.com")

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


def test_403_is_reported_as_a_rejected_key_with_the_verified_error_shape() -> None:
    """Verified against the live endpoint: invalid keys answer 403 + errorCode."""
    payload = {
        "requestId": "1137d973",
        "errorMessage": "Incorrect APIKey provided.",
        "errorCode": "Retrieval.InvalidAPIKey",
    }
    attempt = Attempt(status_code=403, payload=payload, raw_text=json.dumps(payload))
    message = describe_failure(attempt)
    assert "API key was rejected" in message
    assert "Incorrect APIKey" in message
    assert "Retrieval.InvalidAPIKey" in message


def test_401_is_reported_as_a_rejected_key() -> None:
    attempt = Attempt(status_code=401, payload={"errorMessage": "unauthorized", "errorCode": "X"})
    assert "API key was rejected" in describe_failure(attempt)


def test_429_is_reported_without_retrying() -> None:
    attempt = Attempt(status_code=429, payload={"errorMessage": "too many requests"})
    message = describe_failure(attempt)
    assert "rate limited" in message
    assert "does not retry" in message


def test_400_is_reported_as_a_rejected_request() -> None:
    attempt = Attempt(status_code=400, payload={"errorMessage": "invalid engineType"})
    message = describe_failure(attempt)
    assert "HTTP 400" in message
    assert "invalid engineType" in message


@pytest.mark.parametrize("status", [500, 502, 503])
def test_5xx_is_reported_as_an_aliyun_failure(status: int) -> None:
    attempt = Attempt(status_code=status, payload={"errorMessage": "internal"})
    message = describe_failure(attempt)
    assert f"HTTP {status}" in message
    assert "Aliyun failed" in message


def test_a_200_without_page_items_names_the_schema_that_came_back() -> None:
    payload = {"requestId": "x", "webPages": []}
    attempt = Attempt(status_code=200, payload=payload, raw_text=json.dumps(payload))
    message = describe_failure(attempt)
    assert "no result list" in message
    assert "requestId" in message and "webPages" in message


def test_error_message_reads_the_documented_error_shape() -> None:
    assert error_message({"errorMessage": "bad key", "errorCode": "Retrieval.InvalidAPIKey"}) == (
        "bad key (code Retrieval.InvalidAPIKey)"
    )
    assert error_message({"message": "oops"}) == "oops"
    assert error_message({"code": 400}) == "400"
    assert error_message("not a dict") == ""
    assert error_message({}) == ""


# --------------------------------------------------------------------------- #
# dedupe and statistics
# --------------------------------------------------------------------------- #


def outcome(query: str, *items) -> probe.QueryOutcome:
    attempt = ok(*items)
    result = probe.QueryOutcome(query=query, attempt=attempt)
    result.results = collect(attempt, query)
    return result


def test_the_same_url_from_two_queries_is_counted_once() -> None:
    shared = item(link="https://example.com/same")
    summary = summarize([outcome("q1", shared), outcome("q2", shared)], NOW)
    assert summary.raw_results == 2
    assert summary.unique_urls == 1
    assert summary.duplicates == 1


def test_tracking_parameters_do_not_create_a_second_result() -> None:
    summary = summarize(
        [
            outcome("q1", item(link="https://example.com/x?utm_source=aliyun")),
            outcome("q2", item(link="https://example.com/x")),
        ],
        NOW,
    )
    assert summary.unique_urls == 1
    assert summary.duplicates == 1


def test_summary_counts_known_and_discovered_hostnames() -> None:
    summary = summarize(
        [outcome("q1", item(link="https://openai.com/news/x"), item(link="https://newlab.example.com/p"))],
        NOW,
    )
    assert summary.known_sources == 1
    assert summary.discovered == 1


def test_summary_uses_the_link_hostname_not_the_site_name() -> None:
    """hostname is a site *name* in this API, so the domain must come from link."""
    result = collect(ok(item(link="https://www.163.com/dy/article/x.html", hostname="网易")))
    assert result[0].domain == "163.com"
    assert result[0].quality == PORTAL


def test_summary_counts_recency_buckets() -> None:
    summary = summarize(
        [
            outcome(
                "q1",
                item(link="https://a.example.com/1", publishedTime=INSIDE),
                item(link="https://b.example.com/2", publishedTime=OUTSIDE),
                item(link="https://c.example.com/3", publishedTime=""),
            )
        ],
        NOW,
    )
    assert summary.published_known == 2
    assert summary.inside_24h == 1
    assert summary.outside_24h == 1
    assert summary.unknown_publish == 1


def test_a_future_timestamp_is_never_inside_the_last_24h() -> None:
    summary = summarize([outcome("q1", item(publishedTime="2026-10-01T00:00:00+08:00"))], NOW)
    assert summary.inside_24h == 0
    assert summary.outside_24h == 1


def test_summary_counts_quality_buckets_and_the_watchlist() -> None:
    summary = summarize(
        [
            outcome(
                "q1",
                item(link="https://baijiahao.baidu.com/s?id=1"),
                item(link="https://zhuanlan.zhihu.com/p/1"),
                item(link="https://github.com/x/y"),
                item(link="https://openai.com/news/x"),
            )
        ],
        NOW,
    )
    assert summary.quality[PORTAL] == 1
    assert summary.quality[UGC_BLOG] == 1
    assert summary.quality[RESEARCH] == 1
    assert summary.quality[OFFICIAL] == 1
    assert summary.second_hand == 2


def test_watched_counters_keep_the_domains_separate() -> None:
    summary = summarize(
        [
            outcome(
                "q1",
                item(link="https://baijiahao.baidu.com/s?id=1"),
                item(link="https://baijiahao.baidu.com/s?id=2"),
                item(link="https://m.163.com/dy/article/x.html"),
            )
        ],
        NOW,
    )
    assert summary.watched["baijiahao.baidu.com"] == 2
    assert summary.watched["163.com"] == 1
    assert summary.second_hand == 3


def test_tag_coverage_and_genre_distribution_are_counted() -> None:
    summary = summarize(
        [
            outcome(
                "q1",
                item(link="https://a.example.com/1", tags={"genre": "Blog"}),
                item(link="https://b.example.com/2", tags={"genre": "Blog"}),
                item(link="https://c.example.com/3", tags={}),
            )
        ],
        NOW,
    )
    assert summary.tagged == 2
    assert summary.genres["Blog"] == 2


def test_failed_and_skipped_queries_are_counted_separately() -> None:
    failed = probe.QueryOutcome(query="q2", attempt=Attempt(status_code=500, payload={}))
    failed.error = describe_failure(failed.attempt)
    skipped = probe.QueryOutcome(query="q3", skipped="too long")
    summary = summarize([outcome("q1", item()), failed, skipped], NOW)
    assert summary.queries == 3
    assert summary.successful == 1
    assert summary.failed == 1
    assert summary.skipped == 1


def test_the_summary_records_which_engine_was_asked() -> None:
    assert summarize([outcome("q1", item())], NOW).engine == ENGINE_TYPE
    assert summarize([outcome("q1", item())], NOW, engine="Generic").engine == "Generic"

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
        {query: ok(item(link=f"https://example.com/{index}")) for index, query in enumerate(QUERY_POOL)},
        calls,
    )


def test_run_sends_one_request_per_query_to_the_documented_endpoint() -> None:
    calls: list = []
    status = run(api_key="secret", queries=QUERY_POOL, now=NOW, send=all_ok(calls), out=Recorder())
    assert status == 0
    assert len(calls) == len(QUERY_POOL)
    assert all(call["url"] == ENDPOINT for call in calls)
    assert all(call["headers"]["Authorization"] == "Bearer secret" for call in calls)
    assert all(call["payload"]["engineType"] == ENGINE_TYPE for call in calls)
    assert all(call["payload"]["advancedParams"]["endPublishedDate"] == "2026-09-20" for call in calls)


def test_run_keeps_going_after_one_query_fails() -> None:
    responses = {query: ok(item(link=f"https://example.com/{index}")) for index, query in enumerate(QUERY_POOL)}
    responses["AI Agent 最新发布"] = Attempt(status_code=500, payload={"errorMessage": "boom"})
    calls: list = []
    status = run(api_key="secret", queries=QUERY_POOL, now=NOW, send=fake_send(responses, calls), out=Recorder())
    assert len(calls) == len(QUERY_POOL)
    assert status == 0


def test_run_reports_failed_and_successful_queries() -> None:
    responses = {"good": ok(item()), "bad": Attempt(status_code=429, payload={"errorMessage": "slow down"})}
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
        send=fake_send({"q1": ok(item(link="https://example.com/1")), "q2": ok(item(link="https://example.com/2"))}),
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
    run(
        api_key="super-secret-key",
        queries=("q",),
        now=NOW,
        send=fake_send({"q": ok(item())}),
        out=recorder,
    )
    assert "Aliyun CleverSee Web Search Probe" in recorder.text
    assert f"Endpoint: {ENDPOINT}" in recorder.text
    assert "API key: configured" in recorder.text
    assert "super-secret-key" not in recorder.text


def test_run_prints_the_summary_in_the_required_shape() -> None:
    recorder = Recorder()
    run(
        api_key="secret",
        queries=("q1", "q2"),
        now=NOW,
        send=fake_send(
            {
                "q1": ok(item(link="https://openai.com/news/x")),
                "q2": ok(item(link="https://newlab.example.com/p")),
            }
        ),
        out=recorder,
    )
    for expected in (
        "SUMMARY",
        f"Engine: {ENGINE_TYPE}",
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
    ):
        assert expected in recorder.text, expected


def test_run_prints_the_watchlist_and_tags() -> None:
    recorder = Recorder()
    run(
        api_key="secret",
        queries=("q",),
        now=NOW,
        send=fake_send(
            {
                "q": ok(
                    item(link="https://baijiahao.baidu.com/s?id=1"),
                    item(link="https://blog.csdn.net/a/article/details/1"),
                )
            }
        ),
        out=recorder,
    )
    assert "Second-hand / UGC watchlist" in recorder.text
    assert "baijiahao.baidu.com" in recorder.text
    assert "blog.csdn.net" in recorder.text
    assert "Results carrying tags:" in recorder.text
    assert "Genre distribution" in recorder.text


def test_run_prints_discovered_candidates_with_score_and_tags() -> None:
    recorder = Recorder()
    run(
        api_key="secret",
        queries=("q",),
        now=NOW,
        send=fake_send(
            {
                "q": ok(
                    item(
                        title="A brand new robotics lab",
                        link="https://newlab.example.com/post",
                        rerankScore=0.77,
                        tags={"genre": "Blog"},
                    )
                )
            }
        ),
        out=recorder,
    )
    assert "DISCOVERED CANDIDATES" in recorder.text
    assert "newlab.example.com" in recorder.text
    assert "rerank_score: 0.77" in recorder.text
    assert "genre=Blog" in recorder.text


def test_run_prints_no_result_as_an_empty_list_not_an_error() -> None:
    recorder = Recorder()
    status = run(api_key="secret", queries=("q",), now=NOW, send=fake_send({"q": ok()}), out=recorder)
    assert status == 0
    assert "Results: 0" in recorder.text
    assert "(no results to compare)" in recorder.text


def test_run_exits_unusable_when_no_query_succeeds() -> None:
    recorder = Recorder()
    attempt = Attempt(status_code=403, payload={"errorCode": "Retrieval.InvalidAPIKey"})
    status = run(api_key="bad", queries=("q1", "q2"), now=NOW, send=fake_send({"q1": attempt, "q2": attempt}), out=recorder)
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
    monkeypatch.delenv("ALIYUN_SEARCH_API_KEY", raising=False)
    status = main([])
    captured = capsys.readouterr()
    assert status == 2
    assert "Missing environment variable: ALIYUN_SEARCH_API_KEY" in captured.out
    assert "Traceback" not in captured.out
    assert "Traceback" not in captured.err


def test_main_does_not_call_the_api_when_the_key_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALIYUN_SEARCH_API_KEY", raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("the probe must not send a request without a key")

    monkeypatch.setattr(probe, "send_request", forbidden)
    assert main([]) == 2


def test_a_blank_key_counts_as_missing(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setenv("ALIYUN_SEARCH_API_KEY", "   ")
    assert main([]) == 2
    assert "Missing environment variable: ALIYUN_SEARCH_API_KEY" in capsys.readouterr().out


def test_main_never_prints_the_key(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setenv("ALIYUN_SEARCH_API_KEY", "top-secret-value")
    seen: list = []

    def send(url: str, headers: dict, payload: dict, timeout: float) -> Attempt:
        seen.append(headers.get("Authorization"))
        return ok(item())

    monkeypatch.setattr(probe, "send_request", send)
    main(["--timeout", "5"])
    captured = capsys.readouterr()
    assert seen and all(value == "Bearer top-secret-value" for value in seen)
    assert "top-secret-value" not in captured.out
    assert "top-secret-value" not in captured.err


def test_main_defaults_to_the_cn_lite_basic_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALIYUN_SEARCH_API_KEY", "secret")
    engines: list = []

    def send(url: str, headers: dict, payload: dict, timeout: float) -> Attempt:
        engines.append(payload["engineType"])
        return ok(item())

    monkeypatch.setattr(probe, "send_request", send)
    main([])
    assert engines and set(engines) == {ENGINE_TYPE}