"""Phase 10.15: the Web Discovery layer beside the fixed sources.

The probes answered "which search provider is worth using"; this suite pins what
the *production* layer does with the winner. Two rules shape every test here.

**No network, ever.** Discovery sits inside the refresh path, so a test that let
it call Tavily would spend live credits and depend on the internet. Every HTTP
answer is injected: either through the ``send`` seam ``collect_web_discovery``
exposes or through ``httpx.MockTransport`` for the collector itself.

**The fixed digest is never at risk.** Half of these tests are about failure -
a rejected key, a rate limit, a timeout, a renamed field, all ten queries
failing - and each one asserts the same thing: discovery gives up quietly and
the rest of the refresh is unaffected. A discovery layer that can break the
digest is worse than no discovery layer.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.collectors import tavily
from app.collectors.raw import CollectResult, RawArticle
from app.config.discovery import (
    DEFAULT_MAX_CANDIDATES,
    DEFAULT_MAX_PER_DOMAIN,
    DEFAULT_RESULTS_PER_QUERY,
    DEFAULT_TIMEOUT,
    DISCOVERY_QUERIES,
    MAX_RESULTS_PER_QUERY_LIMIT,
    RRF_K,
    WebDiscoverySettings,
    load_web_discovery_settings,
)
from app.config.sources import source_map
from app.jobs.test_tavily_search import QUERY_POOL
from app.pipelines.dedup import dedupe_articles
from app.services.digest_window import DigestWindow
from app.services.web_discovery import (
    DISCOVERY_SOURCE_ID,
    DISCOVERY_SOURCE_NAME,
    UNKNOWN_SOURCE_TYPE,
    DiscoveryCandidate,
    DiscoveryStats,
    candidate_from_hit,
    collect_web_discovery,
    discovery_debug_enabled,
    format_discovery_candidates,
    format_discovery_stats,
    fuse,
    is_non_article_surface,
    is_within_last_24h,
    rank_key,
    rrf_contribution,
    select_candidates,
    to_raw_article,
)

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)

# Tavily answers with RFC 2822 timestamps, so the fixtures use that encoding and
# the tests that care about the wire format say so explicitly.
INSIDE = "Sun, 20 Sep 2026 06:00:00 GMT"
OUTSIDE = "Fri, 18 Sep 2026 06:00:00 GMT"

AI_TITLE = "OpenAI ships a new model for agentic coding"
AI_SNIPPET = "The lab said the model is available today."
NOT_AI_TITLE = "Regional football club wins the cup final"
NOT_AI_SNIPPET = "The match ended two goals to one."


@pytest.fixture(autouse=True)
def ignore_the_developers_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep settings tests from reading the real ``backend/.env``.

    The layer is off by default, but a developer who enabled it locally would
    otherwise see these tests change behaviour with their machine. Every value a
    test needs is set explicitly, so the loader is a no-op.
    """
    monkeypatch.setattr("app.config.discovery.load_dotenv", lambda *args, **kwargs: None)


@pytest.fixture(autouse=True)
def clear_the_discovery_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test from "nothing is configured"."""
    for name in (
        "WEB_DISCOVERY_ENABLED",
        "WEB_DISCOVERY_PROVIDER",
        "WEB_DISCOVERY_RESULTS_PER_QUERY",
        "WEB_DISCOVERY_MAX_CANDIDATES",
        "WEB_DISCOVERY_MAX_PER_DOMAIN",
        "WEB_DISCOVERY_TIMEOUT",
        "TAVILY_API_KEY",
        "AI_DAILY_DEBUG_WEB_DISCOVERY",
    ):
        monkeypatch.delenv(name, raising=False)


def configured(**kwargs) -> WebDiscoverySettings:
    """Settings for a run that really talks to the provider."""
    values = {
        "enabled": True,
        "provider": "tavily",
        "api_key": "test-key",
        "results_per_query": 10,
        "max_candidates": DEFAULT_MAX_CANDIDATES,
        "max_per_domain": DEFAULT_MAX_PER_DOMAIN,
        "timeout": DEFAULT_TIMEOUT,
    }
    values.update(kwargs)
    return WebDiscoverySettings(**values)


def node(url: str, **kwargs) -> dict:
    """One node of the provider's `results` list, in the wire schema.

    The keys are Tavily's, not the dataclass fields, so a fixture that parsed
    here has exercised the real field mapping.
    """
    values = {
        "title": AI_TITLE,
        "url": url,
        "content": AI_SNIPPET,
        "score": 0.81,
        "published_date": INSIDE,
    }
    values.update(kwargs)
    return values


def hit(url: str, **kwargs) -> tavily.TavilyHit:
    """One hit as the collector's dataclass, for tests of the gates themselves."""
    values = {
        "title": AI_TITLE,
        "url": url,
        "published": INSIDE,
        "snippet": AI_SNIPPET,
        "score": "0.81",
    }
    values.update(kwargs)
    return tavily.TavilyHit(**values)


def payload_with(*nodes: dict, key: str = "results") -> dict:
    return {"query": "q", key: list(nodes)}


def ok(*nodes: dict) -> tavily.Attempt:
    payload = payload_with(*nodes)
    return tavily.Attempt(status_code=200, payload=payload, raw_text=json.dumps(payload))


def failing(status: int, detail: object = None) -> tavily.Attempt:
    payload = {"detail": detail if detail is not None else {"error": "nope"}}
    return tavily.Attempt(status_code=status, payload=payload, raw_text=json.dumps(payload))


def by_query(*answers: tavily.Attempt):
    """A transport that answers the n-th query with the n-th answer.

    Keyed by position rather than by query text so a test can say "the first two
    queries work and the third is rate limited" without repeating the query
    strings, which belong to the production pool and not to this file.
    """
    seen: list[str] = []

    def send(url: str, headers: dict, payload: dict, timeout: float) -> tavily.Attempt:
        index = len(seen)
        seen.append(str(payload["query"]))
        if index >= len(answers):
            raise AssertionError("more queries were sent than the test provided answers for")
        return answers[index]

    send.seen = seen  # type: ignore[attr-defined]
    return send


def discover(*answers: tavily.Attempt, queries: tuple[str, ...] = ("q0",), **kwargs):
    """Run one discovery pass against injected answers."""
    settings = kwargs.pop("settings", configured())
    send = by_query(*answers)
    outcome = collect_web_discovery(NOW, settings=settings, queries=queries, send=send, **kwargs)
    return outcome

# --------------------------------------------------------------------------- #
# configuration
# --------------------------------------------------------------------------- #


def test_web_discovery_is_off_unless_it_is_switched_on() -> None:
    """The shipped default: a deployment that configures nothing is unchanged."""
    settings = load_web_discovery_settings()
    assert settings.enabled is False
    assert settings.runnable is False


def test_enabling_the_layer_without_a_key_is_not_runnable() -> None:
    settings = WebDiscoverySettings(enabled=True, api_key="")
    assert settings.runnable is False


def test_a_second_provider_is_not_silently_accepted() -> None:
    settings = WebDiscoverySettings(enabled=True, provider="somewhere-else", api_key="k")
    assert settings.runnable is False


def test_the_defaults_match_the_benchmark_the_decision_was_made_on() -> None:
    assert DEFAULT_RESULTS_PER_QUERY == 10
    assert DEFAULT_MAX_CANDIDATES == 24
    assert DEFAULT_MAX_PER_DOMAIN == 2
    assert DEFAULT_TIMEOUT == 15.0
    assert RRF_K == 60


def test_the_query_pool_is_the_benchmark_pool_and_is_shared_not_copied() -> None:
    """One query set, in production, imported by the probes.

    Duplicating the ten queries per probe is how the three benchmark runs would
    silently stop being comparable, so the probes import this tuple and the
    suite asserts the sharing rather than the contents.
    """
    assert len(DISCOVERY_QUERIES) == 10
    assert len(set(DISCOVERY_QUERIES)) == 10
    assert QUERY_POOL is DISCOVERY_QUERIES


def test_an_unparseable_setting_keeps_its_default_instead_of_becoming_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typo must not disable the cap it was meant to tighten."""
    monkeypatch.setenv("WEB_DISCOVERY_MAX_CANDIDATES", "as many as possible")
    monkeypatch.setenv("WEB_DISCOVERY_MAX_PER_DOMAIN", "-3")
    settings = load_web_discovery_settings()
    assert settings.max_candidates == DEFAULT_MAX_CANDIDATES
    assert settings.max_per_domain == DEFAULT_MAX_PER_DOMAIN


def test_results_per_query_is_clamped_to_the_provider_maximum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WEB_DISCOVERY_RESULTS_PER_QUERY", "500")
    assert load_web_discovery_settings().results_per_query == MAX_RESULTS_PER_QUERY_LIMIT


# --------------------------------------------------------------------------- #
# the layer switched off, and switched on but unusable
# --------------------------------------------------------------------------- #


def test_disabled_discovery_returns_nothing_and_makes_no_request() -> None:
    """``None`` rather than an empty result: no report row, no HTTP call."""

    def forbidden(*args, **kwargs):
        raise AssertionError("a disabled layer must not send anything")

    assert (
        collect_web_discovery(
            NOW,
            settings=WebDiscoverySettings(enabled=False, api_key="k"),
            queries=("q",),
            send=forbidden,
        )
        is None
    )


def test_enabled_without_a_key_reports_once_and_skips(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("a layer with no key must not send anything")

    with caplog.at_level("WARNING"):
        outcome = collect_web_discovery(
            NOW,
            settings=WebDiscoverySettings(enabled=True, api_key=""),
            queries=("q1", "q2"),
            send=forbidden,
        )

    assert outcome is not None
    assert outcome.report.success is False
    assert outcome.report.error == "TAVILY_API_KEY is not configured"
    assert outcome.stats.queries == 2
    assert outcome.stats.successful_queries == 0
    assert outcome.candidates == []
    assert "TAVILY_API_KEY is missing" in caplog.text


def test_an_unimplemented_provider_reports_and_skips() -> None:
    outcome = collect_web_discovery(
        NOW,
        settings=WebDiscoverySettings(enabled=True, provider="not-tavily", api_key="k"),
        queries=("q",),
        send=lambda *a, **k: pytest.fail("an unknown provider must not be called"),
    )
    assert outcome is not None
    assert outcome.report.success is False
    assert "not-tavily" in (outcome.report.error or "")


def test_the_discovery_report_is_marked_as_discovery() -> None:
    """So the official coverage block can exclude it."""
    outcome = collect_web_discovery(NOW, settings=configured(), queries=("q",), send=by_query(ok(node("https://openai.com/news/a"))))
    assert outcome is not None
    assert outcome.report.discovery is True
    assert outcome.report.source_id == DISCOVERY_SOURCE_ID
    assert outcome.report.source_name == DISCOVERY_SOURCE_NAME
    # Deliberately not the id of any configured source: it is a way of
    # collecting, not a company channel, so the coverage block must not count it.
    assert DISCOVERY_SOURCE_ID not in source_map()


# --------------------------------------------------------------------------- #
# transport
# --------------------------------------------------------------------------- #


class FakeResponse:
    def __init__(self, status_code: int, text: str, payload=None) -> None:
        self.status_code = status_code
        self.text = text
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class FakeClient:
    """Stands in for ``httpx.Client`` so ``send_request`` is tested offline."""

    response: FakeResponse | None = None
    error: Exception | None = None
    seen: dict = {}

    def __init__(self, *args, **kwargs) -> None:
        FakeClient.seen = {"args": args, "kwargs": kwargs}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, headers=None, json=None):
        FakeClient.seen["url"] = url
        FakeClient.seen["headers"] = headers
        FakeClient.seen["json"] = json
        if FakeClient.error is not None:
            raise FakeClient.error
        assert FakeClient.response is not None
        return FakeClient.response


@pytest.fixture
def fake_http(monkeypatch: pytest.MonkeyPatch) -> type[FakeClient]:
    FakeClient.response = None
    FakeClient.error = None
    FakeClient.seen = {}
    monkeypatch.setattr(tavily.httpx, "Client", FakeClient)
    return FakeClient


def test_send_request_reads_a_200_body(fake_http: type[FakeClient]) -> None:
    fake_http.response = FakeResponse(200, '{"results": []}', {"results": []})
    attempt = tavily.send_request(tavily.ENDPOINT, {}, {"query": "q"}, 5.0)
    assert attempt.status_code == 200
    assert attempt.parsed is True
    assert attempt.payload == {"results": []}
    assert fake_http.seen["url"] == tavily.ENDPOINT


def test_send_request_never_raises_on_a_timeout(fake_http: type[FakeClient]) -> None:
    fake_http.error = httpx.ReadTimeout("too slow")
    attempt = tavily.send_request(tavily.ENDPOINT, {}, {"query": "q"}, 5.0)
    assert attempt.status_code is None
    assert "timed out after 5s" in attempt.transport_error
    assert "timed out" in tavily.describe_failure(attempt)


def test_send_request_never_raises_on_a_connection_error(fake_http: type[FakeClient]) -> None:
    fake_http.error = httpx.ConnectError("no route to host")
    attempt = tavily.send_request(tavily.ENDPOINT, {}, {"query": "q"}, 5.0)
    assert attempt.transport_error.startswith("connection failed")
    assert "connection failed" in tavily.describe_failure(attempt)


def test_send_request_reports_a_non_json_body(fake_http: type[FakeClient]) -> None:
    """A 200 with an HTML body is a usable diagnosis, not an exception."""
    fake_http.response = FakeResponse(200, "<html>gateway timeout</html>")
    attempt = tavily.send_request(tavily.ENDPOINT, {}, {"query": "q"}, 5.0)
    assert attempt.status_code == 200
    assert attempt.parsed is False
    assert "not JSON" in tavily.describe_failure(attempt)


@pytest.mark.parametrize(
    ("status", "detail", "expected"),
    [
        (401, {"error": "Unauthorized: missing or invalid API key."}, "the API key was rejected"),
        (403, {"error": "Forbidden"}, "the API key was rejected"),
        (429, {"error": "Too many requests"}, "rate limited, and discovery does not retry"),
        (400, {"error": "Invalid topic"}, "the request was rejected"),
        (422, [{"loc": ["body", "topic"], "msg": "unexpected value"}], "the request was rejected"),
        (500, {"error": "internal"}, "Tavily failed"),
        (503, {"error": "unavailable"}, "Tavily failed"),
    ],
)
def test_every_documented_failure_gets_a_readable_reason(
    status: int, detail: object, expected: str
) -> None:
    attempt = failing(status, detail)
    assert expected in tavily.describe_failure(attempt)


def test_a_200_without_a_results_list_is_reported_as_a_schema_change() -> None:
    """A renamed field must not look like a quiet news day."""
    attempt = tavily.Attempt(status_code=200, payload={"answer": "x", "web_results": [1]}, raw_text="{}")
    message = tavily.describe_failure(attempt)
    assert "no results list" in message
    assert "answer, web_results" in message


def test_the_auth_headers_use_the_documented_bearer_scheme() -> None:
    headers = tavily.auth_headers("secret-key")
    assert headers["Authorization"] == "Bearer secret-key"
    assert headers["Content-Type"] == "application/json"


def test_the_key_is_never_part_of_a_failure_message() -> None:
    attempt = failing(401, {"error": "Unauthorized: missing or invalid API key."})
    message = tavily.describe_failure(attempt)
    assert "secret" not in message
    assert tavily.error_message({"detail": {"error": "x"}}) == "x"

# --------------------------------------------------------------------------- #
# the funnel: provider hit -> 24h -> AI -> dedup -> RRF -> caps
# --------------------------------------------------------------------------- #


def test_a_normal_run_turns_hits_into_candidates() -> None:
    outcome = discover(
        ok(node("https://openai.com/news/a"), node("https://openai.com/news/b")),
        queries=("q0",),
    )
    assert outcome is not None
    assert outcome.stats.queries == 1
    assert outcome.stats.successful_queries == 1
    assert outcome.stats.failed_queries == 0
    assert outcome.stats.raw_results == 2
    assert outcome.stats.inside_24h == 2
    assert outcome.stats.unique_urls == 2
    assert outcome.stats.selected == 2
    assert {article.url for article in outcome.report.valid} == {
        "https://openai.com/news/a",
        "https://openai.com/news/b",
    }


def test_an_empty_response_is_a_success_with_no_candidates() -> None:
    outcome = discover(ok(), queries=("q0",))
    assert outcome is not None
    assert outcome.stats.successful_queries == 1
    assert outcome.stats.raw_results == 0
    assert outcome.stats.selected == 0
    assert outcome.candidates == []
    assert outcome.report.success is True


def test_one_failed_query_does_not_stop_the_others() -> None:
    """The failure is reported against its own query and the run continues."""
    outcome = discover(
        failing(429),
        ok(node("https://openai.com/news/a")),
        queries=("q0", "q1"),
    )
    assert outcome is not None
    assert outcome.stats.successful_queries == 1
    assert outcome.stats.failed_queries == 1
    assert outcome.stats.selected == 1
    assert len(outcome.errors) == 1
    assert outcome.errors[0].startswith("q0:")
    assert "rate limited" in outcome.errors[0]
    assert outcome.report.success is True


def test_every_query_failing_is_reported_and_produces_no_candidates() -> None:
    outcome = discover(failing(401), failing(401), queries=("q0", "q1"))
    assert outcome is not None
    assert outcome.report.success is False
    assert outcome.stats.successful_queries == 0
    assert outcome.stats.failed_queries == 2
    assert outcome.candidates == []
    assert outcome.report.valid == []


def test_a_transport_failure_is_one_failed_query_not_an_exception() -> None:
    """A timeout is data for this layer, never an error the refresh has to catch."""
    timeout = tavily.Attempt(transport_error="timed out after 15s")
    outcome = discover(timeout, ok(node("https://openai.com/news/a")), queries=("q0", "q1"))
    assert outcome is not None
    assert outcome.stats.failed_queries == 1
    assert "timed out" in outcome.errors[0]
    assert outcome.stats.selected == 1


def test_a_non_json_body_is_a_failed_query() -> None:
    broken = tavily.Attempt(status_code=200, parsed=False, raw_text="<html>")
    outcome = discover(broken, queries=("q0",))
    assert outcome is not None
    assert outcome.stats.failed_queries == 1
    assert "not JSON" in outcome.errors[0]


def test_a_schema_change_is_visible_and_not_silently_empty() -> None:
    """A 200 whose list was renamed fails rather than reporting a quiet day."""
    renamed = tavily.Attempt(status_code=200, payload={"web_results": []}, raw_text="{}")
    outcome = discover(renamed, queries=("q0",))
    assert outcome is not None
    assert outcome.stats.failed_queries == 1
    assert "no results list" in outcome.errors[0]


def test_a_hit_without_a_url_is_dropped_by_the_parser() -> None:
    outcome = discover(ok(node(""), node("https://openai.com/news/b")), queries=("q0",))
    assert outcome is not None
    assert outcome.stats.raw_results == 1
    assert outcome.stats.selected == 1


def test_a_social_surface_is_rejected_before_anything_else() -> None:
    outcome = discover(
        ok(node("https://www.facebook.com/somepost"), node("https://openai.com/news/a")),
        queries=("q0",),
    )
    assert outcome is not None
    assert outcome.stats.dropped_social == 1
    assert outcome.stats.inside_24h == 1
    assert [article.domain if hasattr(article, "domain") else article.url for article in outcome.candidates] == [
        "openai.com"
    ]


# --------------------------------------------------------------------------- #
# time
# --------------------------------------------------------------------------- #


def test_the_rolling_window_is_now_minus_24h_exclusive() -> None:
    assert is_within_last_24h(NOW - timedelta(hours=1), NOW) is True
    assert is_within_last_24h(NOW - timedelta(hours=23, minutes=59), NOW) is True
    # Exactly 24h old is outside: the bound is exclusive, like the issue window.
    assert is_within_last_24h(NOW - timedelta(hours=24), NOW) is False
    assert is_within_last_24h(NOW - timedelta(hours=25), NOW) is False


def test_a_future_timestamp_is_never_recent() -> None:
    assert is_within_last_24h(NOW + timedelta(minutes=1), NOW) is False


def test_an_unknown_time_is_not_recent() -> None:
    assert is_within_last_24h(None, NOW) is False


def test_the_provider_is_not_trusted_about_time() -> None:
    """``time_range=day`` is a request; the local check is the rule."""
    outcome = discover(
        ok(
            node("https://openai.com/news/old", published_date=OUTSIDE),
            node("https://openai.com/news/now", published_date=INSIDE),
        ),
        queries=("q0",),
    )
    assert outcome is not None
    assert outcome.stats.raw_results == 2
    assert outcome.stats.dropped_outside_window == 1
    assert outcome.stats.inside_24h == 1
    assert [candidate.url for candidate in outcome.candidates] == ["https://openai.com/news/now"]


def test_a_hit_without_a_publish_date_is_dropped_and_counted() -> None:
    """Discovery is a supplement; it does not buy recall with undated pages."""
    outcome = discover(
        ok(node("https://openai.com/news/undated", published_date=None)),
        queries=("q0",),
    )
    assert outcome is not None
    assert outcome.stats.dropped_missing_time == 1
    assert outcome.stats.inside_24h == 0
    assert outcome.candidates == []


def test_an_rfc2822_timestamp_is_understood() -> None:
    """The wire format Tavily actually sends."""
    candidate = candidate_from_hit(hit("https://openai.com/news/a", published="Sun, 20 Sep 2026 06:00:00 GMT"))
    assert candidate.published_at == datetime(2026, 9, 20, 6, 0, tzinfo=timezone.utc)


def test_an_unrecognised_timestamp_is_unknown_rather_than_invented() -> None:
    assert tavily.normalize_published("not a date") == "not a date"
    assert tavily.published_at("not a date") is None
    assert tavily.published_at(None) is None
    assert tavily.published_at("") is None


def test_the_discovery_window_is_independent_of_the_issue_window() -> None:
    """The 24h gate is a provider-quality gate; the issue window still decides.

    A candidate that survives discovery can still be outside the digest's own
    window, and that is the pipeline's business rather than this layer's.
    """
    outcome = discover(ok(node("https://openai.com/news/a", published_date=INSIDE)), queries=("q0",))
    assert outcome is not None
    window = DigestWindow(start=NOW - timedelta(hours=1), end=NOW)
    assert outcome.report.valid[0].published_at is not None
    assert window.contains(outcome.report.valid[0].published_at) is False


# --------------------------------------------------------------------------- #
# AI relevance
# --------------------------------------------------------------------------- #


def test_an_ai_result_is_kept() -> None:
    outcome = discover(ok(node("https://openai.com/news/a")), queries=("q0",))
    assert outcome is not None
    assert outcome.stats.dropped_not_ai == 0
    assert outcome.stats.selected == 1


def test_an_unrelated_result_is_dropped_and_counted() -> None:
    unrelated = node(
        "https://example-outlet.test/sport",
        title=NOT_AI_TITLE,
        content=NOT_AI_SNIPPET,
    )
    outcome = discover(ok(unrelated, node("https://openai.com/news/a")), queries=("q0",))
    assert outcome is not None
    assert outcome.stats.inside_24h == 2
    assert outcome.stats.dropped_not_ai == 1
    assert outcome.stats.selected == 1


def test_the_ai_check_reads_the_snippet_as_well_as_the_title() -> None:
    """A vague headline with an obviously AI snippet is still AI news."""
    from app.pipelines.ai_filter import is_ai_related

    vague = node(
        "https://example-outlet.test/x",
        title="A company announced something",
        content="The large language model ships today.",
    )
    assert is_ai_related(vague["title"], vague["content"]) is True
    outcome = discover(ok(vague), queries=("q0",))
    assert outcome is not None
    assert outcome.stats.selected == 1


# --------------------------------------------------------------------------- #
# dedup
# --------------------------------------------------------------------------- #


def test_the_same_url_found_by_two_queries_is_one_candidate() -> None:
    outcome = discover(
        ok(node("https://openai.com/news/a")),
        ok(node("https://openai.com/news/a")),
        queries=("q0", "q1"),
    )
    assert outcome is not None
    assert outcome.stats.raw_results == 2
    assert outcome.stats.unique_urls == 1
    assert outcome.stats.matched_multiple_queries == 1
    assert outcome.candidates[0].hits == 2
    assert len(outcome.candidates[0].matched_queries) == 2


def test_tracking_parameters_do_not_make_a_second_candidate() -> None:
    """Canonicalization is the existing pipeline's, not a second implementation."""
    outcome = discover(
        ok(node("https://openai.com/news/a?utm_source=newsletter")),
        ok(node("https://openai.com/news/a")),
        queries=("q0", "q1"),
    )
    assert outcome is not None
    assert outcome.stats.unique_urls == 1
    assert outcome.candidates[0].canonical_url == "https://openai.com/news/a"


def test_two_different_pages_stay_two_candidates() -> None:
    outcome = discover(
        ok(node("https://openai.com/news/a"), node("https://openai.com/news/b")),
        queries=("q0",),
    )
    assert outcome is not None
    assert outcome.stats.unique_urls == 2


def test_a_candidate_keeps_the_queries_that_found_it() -> None:
    outcome = discover(
        ok(node("https://openai.com/news/a")),
        ok(node("https://openai.com/news/a")),
        queries=("first topic", "second topic"),
    )
    assert outcome is not None
    assert sorted(outcome.candidates[0].matched_queries) == ["first topic", "second topic"]

# --------------------------------------------------------------------------- #
# RRF
# --------------------------------------------------------------------------- #


def test_the_rrf_constant_damps_the_top_of_one_list() -> None:
    assert rrf_contribution(1) == pytest.approx(1 / 61)
    assert rrf_contribution(2) == pytest.approx(1 / 62)
    assert rrf_contribution(1) > rrf_contribution(2)


def test_agreeing_across_queries_beats_ranking_first_in_one() -> None:
    """The whole reason for fusing rather than sorting on one query's order.

    A page three different topic queries returned is a hot-story signal; a page
    one query happened to rank first is one query's opinion.
    """
    shared = DiscoveryCandidate(canonical_url="https://a.test/x", matched_queries=["a", "b", "c"], query_ranks=[1, 2, 3])
    single = DiscoveryCandidate(canonical_url="https://b.test/y", matched_queries=["a"], query_ranks=[1])
    fuse([shared, single])
    assert shared.rrf_score > single.rrf_score
    assert shared.rrf_score == pytest.approx(1 / 61 + 1 / 62 + 1 / 63)


def test_two_queries_agreeing_still_beat_one_first_place() -> None:
    shared = DiscoveryCandidate(canonical_url="https://a.test/x", query_ranks=[9, 9])
    single = DiscoveryCandidate(canonical_url="https://b.test/y", query_ranks=[1])
    fuse([shared, single])
    assert shared.rrf_score > single.rrf_score


def test_the_same_url_is_counted_once_per_query() -> None:
    """A URL listed twice by one query contributes once, not twice."""
    duplicated = DiscoveryCandidate(canonical_url="https://a.test/x", query_ranks=[1, 5])
    once = DiscoveryCandidate(canonical_url="https://b.test/y", query_ranks=[1])
    fuse([duplicated, once])
    assert duplicated.rrf_score > once.rrf_score


def test_the_provider_score_cannot_change_the_order() -> None:
    """Tavily's ``score`` is diagnosis only: it is not comparable between queries."""
    strong_provider_score = DiscoveryCandidate(
        canonical_url="https://low.test/x", query_ranks=[10], provider_score="0.99"
    )
    weak_provider_score = DiscoveryCandidate(
        canonical_url="https://high.test/y", query_ranks=[1], provider_score="0.01"
    )
    fuse([strong_provider_score, weak_provider_score])
    ordered = sorted([strong_provider_score, weak_provider_score], key=rank_key)
    assert ordered[0] is weak_provider_score


def test_the_order_is_deterministic_when_the_score_ties() -> None:
    """Same RRF, same timestamp: the canonical URL still decides."""
    now = NOW - timedelta(hours=2)
    first = DiscoveryCandidate(canonical_url="https://a.test/x", url="https://a.test/x", query_ranks=[1], published_at=now)
    second = DiscoveryCandidate(canonical_url="https://b.test/y", url="https://b.test/y", query_ranks=[1], published_at=now)
    fuse([first, second])
    assert [candidate.canonical_url for candidate in sorted([second, first], key=rank_key)] == [
        "https://a.test/x",
        "https://b.test/y",
    ]


def test_recency_ties_break_on_the_timestamp_before_the_url() -> None:
    older = DiscoveryCandidate(
        canonical_url="https://a.test/older",
        url="https://a.test/older",
        query_ranks=[1],
        published_at=NOW - timedelta(hours=20),
    )
    newer = DiscoveryCandidate(
        canonical_url="https://z.test/newer",
        url="https://z.test/newer",
        query_ranks=[1],
        published_at=NOW - timedelta(hours=1),
    )
    fuse([older, newer])
    assert sorted([older, newer], key=rank_key)[0] is newer


def test_the_run_ranks_by_agreement_not_by_position_in_one_query() -> None:
    """End to end: the two-query page comes first even though it ranked lower."""
    outcome = discover(
        # q0 ranks the single-query page first and the shared page third.
        ok(node("https://solo.test/a"), node("https://other.test/b"), node("https://shared.test/c")),
        # q1 also returns the shared page.
        ok(node("https://shared.test/c")),
        queries=("q0", "q1"),
    )
    assert outcome is not None
    assert outcome.candidates[0].domain == "shared.test"
    assert outcome.stats.matched_multiple_queries == 1


# --------------------------------------------------------------------------- #
# domain diversity and the candidate cap
# --------------------------------------------------------------------------- #


def test_one_domain_may_not_fill_the_allowance() -> None:
    candidates = [
        DiscoveryCandidate(canonical_url=f"https://portal.test/{index}", domain="portal.test", query_ranks=[index + 1])
        for index in range(8)
    ]
    for index, candidate in enumerate(candidates):
        candidate.published_at = NOW - timedelta(minutes=index + 1)
    fuse(candidates)
    candidates.sort(key=rank_key)
    selected, dropped_domain, dropped_cap = select_candidates(
        candidates, max_per_domain=2, max_candidates=24
    )
    assert len(selected) == 2
    assert dropped_domain == 6
    assert dropped_cap == 0
    assert {candidate.domain for candidate in selected} == {"portal.test"}


def test_the_domain_cap_keeps_the_best_page_of_the_domain() -> None:
    best = DiscoveryCandidate(canonical_url="https://portal.test/best", domain="portal.test", query_ranks=[1])
    second = DiscoveryCandidate(canonical_url="https://portal.test/second", domain="portal.test", query_ranks=[2])
    worst = DiscoveryCandidate(canonical_url="https://portal.test/worst", domain="portal.test", query_ranks=[9])
    for candidate in (best, second, worst):
        candidate.published_at = NOW
    fuse([best, second, worst])
    selected, _, _ = select_candidates(
        sorted([best, second, worst], key=rank_key), max_per_domain=2, max_candidates=24
    )
    assert {candidate.canonical_url for candidate in selected} == {
        "https://portal.test/best",
        "https://portal.test/second",
    }


def test_other_domains_are_preserved_when_one_is_capped() -> None:
    """The cap reserves room instead of letting one portal crowd out the rest."""
    portal = [
        DiscoveryCandidate(canonical_url=f"https://portal.test/{index}", domain="portal.test", query_ranks=[index + 1])
        for index in range(6)
    ]
    others = [
        DiscoveryCandidate(canonical_url=f"https://outlet{index}.test/x", domain=f"outlet{index}.test", query_ranks=[10])
        for index in range(4)
    ]
    for index, candidate in enumerate(portal + others):
        candidate.published_at = NOW - timedelta(minutes=index)
    fuse(portal + others)
    selected, dropped_domain, _ = select_candidates(
        sorted(portal + others, key=rank_key), max_per_domain=2, max_candidates=24
    )
    assert dropped_domain == 4
    assert {candidate.domain for candidate in selected} == {
        "portal.test",
        "outlet0.test",
        "outlet1.test",
        "outlet2.test",
        "outlet3.test",
    }


def test_the_final_cap_is_the_configured_maximum() -> None:
    candidates = [
        DiscoveryCandidate(canonical_url=f"https://outlet{index}.test/x", domain=f"outlet{index}.test", query_ranks=[index + 1])
        for index in range(30)
    ]
    for index, candidate in enumerate(candidates):
        candidate.published_at = NOW - timedelta(minutes=index)
    fuse(candidates)
    selected, _, dropped_cap = select_candidates(
        sorted(candidates, key=rank_key), max_per_domain=2, max_candidates=5
    )
    assert len(selected) == 5
    assert dropped_cap == 25


def test_a_run_never_hands_more_than_the_cap_to_the_pipeline() -> None:
    """~100 raw hits must narrow to the configured allowance, not to 100."""
    nodes = [
        node(f"https://outlet{index}.test/story", title=f"OpenAI news number {index}")
        for index in range(40)
    ]
    outcome = discover(ok(*nodes), queries=("q0",), settings=configured(max_candidates=6, max_per_domain=2))
    assert outcome is not None
    assert outcome.stats.raw_results == 40
    assert outcome.stats.unique_urls == 40
    assert outcome.stats.selected == 6
    assert len(outcome.report.valid) == 6
    assert outcome.stats.dropped_candidate_cap == 34


def test_a_single_domain_run_is_capped_too() -> None:
    nodes = [node(f"https://one-portal.test/{index}") for index in range(20)]
    outcome = discover(ok(*nodes), queries=("q0",), settings=configured(max_per_domain=2))
    assert outcome is not None
    assert outcome.stats.selected == 2
    assert outcome.stats.dropped_domain_cap == 18

# --------------------------------------------------------------------------- #
# source mapping
# --------------------------------------------------------------------------- #


def test_a_configured_domain_reuses_its_own_source_and_type() -> None:
    """So the same story from Tavily and from the vendor's feed merges."""
    article = to_raw_article(
        DiscoveryCandidate(
            title="OpenAI ships a model",
            url="https://openai.com/news/a",
            canonical_url="https://openai.com/news/a",
            domain="openai.com",
        )
    )
    source = source_map()["openai"]
    assert article.source_id == source.id
    assert article.source == source.name
    assert article.source_type == source.source_type
    assert article.source_type == "official"


def test_a_subdomain_of_a_configured_source_is_matched_too() -> None:
    article = to_raw_article(
        DiscoveryCandidate(
            url="https://blog.openai.com/x",
            canonical_url="https://blog.openai.com/x",
            domain="blog.openai.com",
        )
    )
    assert article.source_id == "openai"
    assert article.source_type == "official"


def test_an_unknown_domain_is_media_and_never_official() -> None:
    """A search engine saying a page exists says nothing about who published it."""
    article = to_raw_article(
        DiscoveryCandidate(
            title="A lab nobody configured released a model",
            url="https://brand-new-lab.test/news/model",
            canonical_url="https://brand-new-lab.test/news/model",
            domain="brand-new-lab.test",
        )
    )
    assert article.source_id == "web:brand-new-lab.test"
    assert article.source == "brand-new-lab.test"
    assert article.source_type == UNKNOWN_SOURCE_TYPE
    assert UNKNOWN_SOURCE_TYPE == "media"
    assert UNKNOWN_SOURCE_TYPE in ("official", "research", "media")


def test_the_unknown_source_id_is_not_a_configured_source() -> None:
    article = to_raw_article(DiscoveryCandidate(url="https://x.test/a", canonical_url="https://x.test/a", domain="x.test"))
    assert article.source_id not in source_map()


def test_the_snippet_becomes_the_summary_until_extraction_replaces_it() -> None:
    article = to_raw_article(
        DiscoveryCandidate(
            url="https://openai.com/news/a",
            canonical_url="https://openai.com/news/a",
            domain="openai.com",
            snippet="What the search engine saw.",
        )
    )
    assert article.summary == "What the search engine saw."


def test_a_discovered_article_carries_no_extraction_state() -> None:
    """It is a feed-shaped article, so the pipeline extracts it like any other."""
    article = to_raw_article(DiscoveryCandidate(url="https://x.test/a", canonical_url="https://x.test/a", domain="x.test"))
    assert article.content == ""
    assert article.content_raw == ""
    assert article.content_method == ""


def test_a_known_domain_in_a_run_gets_the_configured_source_type() -> None:
    outcome = discover(
        ok(node("https://www.anthropic.com/news/claude")),
        queries=("q0",),
    )
    assert outcome is not None
    assert outcome.report.valid[0].source_type == "official"
    assert outcome.report.valid[0].source_id == "anthropic"


def test_an_unconfigured_domain_in_a_run_is_media() -> None:
    outcome = discover(ok(node("https://nobody-configured-this.test/x")), queries=("q0",))
    assert outcome is not None
    assert outcome.report.valid[0].source_type == "media"
    assert outcome.report.valid[0].source_id == "web:nobody-configured-this.test"


# --------------------------------------------------------------------------- #
# integration with the existing dedup
# --------------------------------------------------------------------------- #


def raw(
    *,
    source_id: str,
    source: str,
    source_type: str,
    url: str,
    title: str = AI_TITLE,
    published_at: datetime | None = None,
) -> RawArticle:
    return RawArticle(
        source_id=source_id,
        source=source,
        source_type=source_type,
        title=title,
        url=url,
        canonical_url=url,
        published_at=published_at or NOW - timedelta(hours=1),
        summary=AI_SNIPPET,
    )


def test_one_url_from_a_fixed_source_and_discovery_collapses_to_one() -> None:
    """The discovered page is an ordinary article, not a parallel universe."""
    fixed = raw(
        source_id="openai",
        source="OpenAI",
        source_type="official",
        url="https://openai.com/news/a",
    )
    discovered = to_raw_article(
        DiscoveryCandidate(
            title="OpenAI ships a model",
            url="https://openai.com/news/a",
            canonical_url="https://openai.com/news/a",
            domain="openai.com",
            snippet=AI_SNIPPET,
            published_at=NOW - timedelta(hours=1),
        )
    )
    kept = dedupe_articles([fixed, discovered])
    assert len(kept) == 1
    assert kept[0].source_type == "official"
    assert kept[0].source_id == "openai"


def test_official_beats_a_discovered_media_copy_of_the_same_event() -> None:
    """Even when the two URLs differ: same title, same event, official wins."""
    fixed = raw(
        source_id="openai",
        source="OpenAI",
        source_type="official",
        url="https://openai.com/news/announcement",
    )
    discovered = to_raw_article(
        DiscoveryCandidate(
            title=AI_TITLE,
            url="https://a-portal.test/repost-of-the-announcement",
            canonical_url="https://a-portal.test/repost-of-the-announcement",
            domain="a-portal.test",
            snippet=AI_SNIPPET,
            published_at=NOW - timedelta(hours=2),
        )
    )
    kept = dedupe_articles([fixed, discovered])
    assert len(kept) == 1
    assert kept[0].source_id == "openai"
    assert kept[0].source_type == "official"


def test_a_discovered_article_that_shares_nothing_survives_dedup() -> None:
    fixed = raw(
        source_id="openai",
        source="OpenAI",
        source_type="official",
        url="https://openai.com/news/a",
    )
    discovered = to_raw_article(
        DiscoveryCandidate(
            title="A different robotics lab raises a round",
            url="https://another-lab.test/news/funding",
            canonical_url="https://another-lab.test/news/funding",
            domain="another-lab.test",
            snippet="The humanoid robot startup said the round funds a new AI model.",
            published_at=NOW - timedelta(hours=3),
        )
    )
    kept = dedupe_articles([fixed, discovered])
    assert len(kept) == 2


def test_a_discovery_report_is_an_ordinary_collect_result() -> None:
    """The refresh log prints it with the same code path as a fixed source."""
    outcome = discover(ok(node("https://openai.com/news/a")), queries=("q0",))
    assert outcome is not None
    report = outcome.report
    assert isinstance(report, CollectResult)
    assert report.success is True
    assert report.fetched == 1
    assert report.error is None


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #


def test_the_summary_line_carries_the_funnel_a_normal_refresh_logs() -> None:
    stats = DiscoveryStats(
        queries=10,
        successful_queries=10,
        raw_results=88,
        inside_24h=84,
        unique_urls=80,
        selected=24,
    )
    assert stats.summary_line() == (
        "Web discovery: queries=10 ok=10 raw=88 recent=84 unique=80 selected=24"
    )


def test_the_report_block_names_every_stage_of_the_funnel() -> None:
    block = format_discovery_stats(DiscoveryStats(queries=10, successful_queries=10))
    assert block.splitlines() == [
        "Web discovery (Tavily)",
        "Queries: 10",
        "Successful queries: 10",
        "Failed queries: 0",
        "Raw results: 0",
        "Inside rolling 24h: 0",
        "Dropped (no publish time): 0",
        "Dropped (outside 24h): 0",
        "Dropped (not AI): 0",
        "Dropped (social surface): 0",
        "Unique URLs: 0",
        "Matched several queries: 0",
        "Dropped (domain cap): 0",
        "Dropped (candidate cap): 0",
        "Selected: 0",
    ]


def test_the_per_candidate_view_is_what_a_dry_run_reads() -> None:
    """The dry-run's whole point: see the 24 before they reach the pipeline."""
    candidates = [
        DiscoveryCandidate(
            title="OpenAI ships a model",
            url="https://openai.com/news/a",
            canonical_url="https://openai.com/news/a",
            domain="openai.com",
            matched_queries=["q0", "q1"],
            query_ranks=[1, 4],
            published_at=NOW - timedelta(hours=1),
            rrf_score=0.03,
        )
    ]
    block = format_discovery_candidates(candidates)
    assert block.splitlines() == [
        "Web discovery candidates: 1",
        "1. rrf=0.030000 hits=2 domain=openai.com",
        "   title: OpenAI ships a model",
        f"   published_at: {candidates[0].published_at.isoformat()}",
        "   queries: q0, q1",
        "   url: https://openai.com/news/a",
    ]


def test_the_candidate_view_says_so_when_there_is_nothing() -> None:
    assert format_discovery_candidates([]) == "Web discovery candidates: none"


def test_debug_logging_is_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    assert discovery_debug_enabled() is False
    monkeypatch.setenv("AI_DAILY_DEBUG_WEB_DISCOVERY", "1")
    assert discovery_debug_enabled() is True
    monkeypatch.setenv("AI_DAILY_DEBUG_WEB_DISCOVERY", "no")
    assert discovery_debug_enabled() is False


def test_debug_mode_keeps_drops_and_adds_nothing_the_summary_lacks(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """KEEP/DROP lines are per candidate; the summary is unchanged."""
    unrelated = node("https://example-outlet.test/sport", title=NOT_AI_TITLE, content=NOT_AI_SNIPPET)
    with caplog.at_level("INFO"):
        outcome = discover(
            ok(unrelated, node("https://openai.com/news/a")),
            queries=("q0",),
            settings=configured(debug=True),
        )
    assert outcome is not None
    assert "DROP reason=not_ai" in caplog.text
    assert "KEEP rrf=" in caplog.text


def test_debug_is_off_by_default_so_a_normal_refresh_stays_quiet(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("INFO"):
        discover(ok(node("https://openai.com/news/a")), queries=("q0",))
    assert "KEEP rrf=" not in caplog.text
    assert "DROP reason=" not in caplog.text


def test_the_social_reject_list_stays_deliberately_small() -> None:
    """Portals and blogs are judged downstream, not blacklisted here."""
    from app.config.discovery import NON_ARTICLE_DOMAINS

    assert set(NON_ARTICLE_DOMAINS) == {"facebook.com", "instagram.com"}
    for domain in ("facebook.com", "www.facebook.com", "m.facebook.com", "instagram.com"):
        assert is_non_article_surface(domain) is True
    for domain in ("sohu.com", "163.com", "blog.csdn.net", "zhuanlan.zhihu.com", "tieba.baidu.com"):
        assert is_non_article_surface(domain) is False


def test_the_social_match_respects_a_dot_boundary() -> None:
    """``notfacebook.com`` is not Facebook."""
    assert is_non_article_surface("notfacebook.com") is False
    assert is_non_article_surface("facebook.com.evil.test") is False
    assert is_non_article_surface("") is False


# --------------------------------------------------------------------------- #
# the request the layer actually sends
# --------------------------------------------------------------------------- #


def test_the_payload_is_the_one_the_benchmark_validated() -> None:
    payload = tavily.build_payload("AI Agent 最新发布", max_results=10)
    assert payload == {
        "query": "AI Agent 最新发布",
        "topic": "news",
        "search_depth": "basic",
        "time_range": "day",
        "max_results": 10,
        "include_answer": False,
        "include_raw_content": False,
        "include_images": False,
        "include_published_date": True,
    }


def test_the_payload_carries_no_removed_or_pinned_date_parameter() -> None:
    payload = json.dumps(tavily.build_payload("q", max_results=10))
    assert '"days"' not in payload
    assert "start_date" not in payload and "end_date" not in payload


def test_the_payload_does_not_exclude_the_watched_domains() -> None:
    """Round one measured raw recall; the layer must keep doing so."""
    payload = tavily.build_payload("q", max_results=10)
    assert "exclude_domains" not in payload
    assert "include_domains" not in payload


def test_the_run_sends_the_configured_result_count_and_timeout() -> None:
    seen: list[tuple[str, float]] = []
    headers_seen: list[dict] = []

    def send(url: str, headers: dict, payload: dict, timeout: float) -> tavily.Attempt:
        seen.append((str(payload["max_results"]), timeout))
        headers_seen.append(headers)
        return ok()

    collect_web_discovery(
        NOW,
        settings=configured(results_per_query=7, timeout=9.5),
        queries=("q0",),
        send=send,
    )
    assert seen == [("7", 9.5)]
    assert headers_seen[0]["Authorization"] == "Bearer test-key"
    assert headers_seen[0]["Content-Type"] == "application/json"


def test_the_layer_asks_every_query_in_the_pool() -> None:
    """Cheap to assert, and the one thing that would silently shrink the funnel."""
    asked: list[str] = []

    def send(url: str, headers: dict, payload: dict, timeout: float) -> tavily.Attempt:
        asked.append(str(payload["query"]))
        return ok()

    collect_web_discovery(NOW, settings=configured(), send=send)
    assert asked == list(DISCOVERY_QUERIES)


def test_the_endpoint_is_the_official_tavily_search_api() -> None:
    assert tavily.ENDPOINT == "https://api.tavily.com/search"

# --------------------------------------------------------------------------- #
# integration: the refresh, the report, and the coverage block
# --------------------------------------------------------------------------- #


def discovery_outcome(
    *articles: RawArticle,
    success: bool = True,
    error: str | None = None,
    candidates: list | None = None,
):
    """A discovery result shaped exactly like the real one.

    `candidates` is what the store keeps for the debug view; `articles` is
    what the report carries. A test that only cares about the pipeline can pass
    articles alone, and the dry-run test passes the candidates it wants printed.
    """
    from app.services.web_discovery import DiscoveryOutcome

    return DiscoveryOutcome(
        report=CollectResult(
            source_id=DISCOVERY_SOURCE_ID,
            source_name=DISCOVERY_SOURCE_NAME,
            success=success,
            error=error,
            fetched=len(articles),
            valid=list(articles),
            discovery=True,
        ),
        stats=DiscoveryStats(
            queries=10,
            successful_queries=9,
            raw_results=88,
            inside_24h=84,
            unique_urls=80,
            selected=len(candidates or articles),
        ),
        candidates=list(candidates or []),
        errors=[error] if error else [],
    )


def discovery_store():
    """A fresh store per test: its discovery state is per instance."""
    from app.services.digest_store import DigestStore

    return DigestStore()


def test_a_refresh_with_discovery_off_makes_no_request_and_adds_no_row(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """The shipped default: an unchanged refresh, down to the requests it makes.

    The layer is asked on every refresh - that is what lets it read its own
    setting - but a disabled layer must not reach the provider and must not add
    a report row, so the logs and the funnel are exactly what they were before
    this module existed.
    """

    def forbidden(*args, **kwargs):
        raise AssertionError("a disabled layer must not send anything")

    monkeypatch.setattr("app.collectors.tavily.send_request", forbidden)
    monkeypatch.setenv("WEB_DISCOVERY_ENABLED", "false")
    from tests.conftest import FROZEN_NOW, day_feeds, make_fixture_fetch
    from app.services.digest_window import DigestWindow

    openai, deepmind, huggingface = day_feeds("2026-09-11")
    store = discovery_store()
    window = DigestWindow(start=FROZEN_NOW - timedelta(hours=24), end=FROZEN_NOW)
    _news, reports = store.collect_news(window, FROZEN_NOW, make_fixture_fetch(openai, deepmind, huggingface))
    assert all(not getattr(report, "discovery", False) for report in reports)
    assert store.last_discovery_stats is None
    assert store.last_error is None


def test_discovery_articles_join_the_same_pipeline_as_the_fixed_sources(
    patch_rss_feeds, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.conftest import FROZEN_NOW, day_feeds, make_fixture_fetch
    from app.services.digest_window import DigestWindow

    discovered = to_raw_article(
        DiscoveryCandidate(
            title="A previously unknown lab releases an agent model",
            url="https://brand-new-lab.test/news/agent",
            canonical_url="https://brand-new-lab.test/news/agent",
            domain="brand-new-lab.test",
            snippet="The company said the agent model is available today.",
            published_at=FROZEN_NOW - timedelta(hours=2),
        )
    )
    monkeypatch.setattr(
        "app.services.digest_store.collect_web_discovery",
        lambda *args, **kwargs: discovery_outcome(discovered),
    )
    openai, deepmind, huggingface = day_feeds("2026-09-11")
    store = discovery_store()
    window = DigestWindow(start=FROZEN_NOW - timedelta(hours=24), end=FROZEN_NOW)
    news_items, reports = store.collect_news(
        window, FROZEN_NOW, make_fixture_fetch(openai, deepmind, huggingface)
    )

    assert any(getattr(report, "discovery", False) for report in reports)
    assert store.last_discovery_stats is not None
    assert any(item.url == "https://brand-new-lab.test/news/agent" for item in news_items)
    assert store.last_error is None


def test_a_discovery_failure_does_not_fail_the_refresh(
    patch_rss_feeds, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tavily 挂了，今天日报不能也挂."""
    from tests.conftest import FROZEN_NOW, day_feeds, make_fixture_fetch
    from app.services.digest_window import DigestWindow

    monkeypatch.setattr(
        "app.services.digest_store.collect_web_discovery",
        lambda *args, **kwargs: discovery_outcome(
            success=False, error="q0: HTTP 401: the API key was rejected"
        ),
    )
    openai, deepmind, huggingface = day_feeds("2026-09-11")
    store = discovery_store()
    window = DigestWindow(start=FROZEN_NOW - timedelta(hours=24), end=FROZEN_NOW)
    news_items, reports = store.collect_news(
        window, FROZEN_NOW, make_fixture_fetch(openai, deepmind, huggingface)
    )

    # The fixed sources still produced their news...
    assert news_items
    # ...and the discovery outage is not counted against them.
    assert store.last_error is None
    fixed = [report for report in reports if not getattr(report, "discovery", False)]
    assert all(report.success for report in fixed)


def test_the_official_coverage_block_never_counts_the_discovery_layer() -> None:
    """Tavily is not a company channel, so it must not inflate coverage."""
    from app.services.source_health import build_coverage, build_report

    report = build_report(
        [
            CollectResult(source_id="openai", source_name="OpenAI", success=True, valid=[object()]),
            CollectResult(
                source_id=DISCOVERY_SOURCE_ID,
                source_name=DISCOVERY_SOURCE_NAME,
                success=True,
                valid=[object()],
                discovery=True,
            ),
        ]
    )
    rows = build_coverage(report)
    assert {row.organization for row in rows} == {"openai"}
    assert DISCOVERY_SOURCE_NAME not in {row.source_name for row in rows}


def test_the_source_table_still_shows_the_discovery_row() -> None:
    """It is reported like a source even though it is not counted as one."""
    from app.services.source_health import format_source_health, build_report

    report = build_report(
        [
            CollectResult(source_id="openai", source_name="OpenAI", success=True, valid=[object()]),
            CollectResult(
                source_id=DISCOVERY_SOURCE_ID,
                source_name=DISCOVERY_SOURCE_NAME,
                success=True,
                valid=[object(), object()],
                discovery=True,
            ),
        ]
    )
    table = format_source_health(report)
    assert DISCOVERY_SOURCE_NAME in table
    assert "Web discovery (Tavily)" not in table


# --------------------------------------------------------------------------- #
# nothing new is invented for the database or the API
# --------------------------------------------------------------------------- #


def test_discovery_does_not_add_a_source_type() -> None:
    """A fourth class would pollute event dedup, media selection and the client."""
    from app.config.sources import NEWS_SOURCE_TYPES

    assert NEWS_SOURCE_TYPES == ("official", "research", "media")
    assert UNKNOWN_SOURCE_TYPE in NEWS_SOURCE_TYPES


def test_discovery_does_not_add_a_database_column() -> None:
    """The funnel is refresh diagnostics; SQLite still stores ordinary articles."""
    from app.models import NewsItem

    columns = set(NewsItem.__dataclass_fields__) if hasattr(NewsItem, "__dataclass_fields__") else set()
    if columns:
        for field_name in ("rrf_score", "matched_queries", "discovery_provider", "query_ranks"):
            assert field_name not in columns


def test_discovery_returns_none_rather_than_an_empty_report() -> None:
    """``None`` is what keeps an off deployment byte-identical to the old one."""
    assert (
        collect_web_discovery(
            NOW, settings=WebDiscoverySettings(enabled=False), queries=("q",), send=lambda *a: ok()
        )
        is None
    )

# --------------------------------------------------------------------------- #
# the read-only dry run
# --------------------------------------------------------------------------- #


def test_the_dry_run_refuses_to_run_while_the_layer_is_off(
    capsys: pytest.CaptureFixture,
) -> None:
    from app.jobs import web_discovery_dry_run as dry_run

    assert dry_run.run(settings=WebDiscoverySettings(enabled=False)) == dry_run.NOT_RUNNABLE_EXIT
    assert "switched off" in capsys.readouterr().out


def test_the_dry_run_refuses_to_run_without_a_key(capsys: pytest.CaptureFixture) -> None:
    from app.jobs import web_discovery_dry_run as dry_run

    status = dry_run.run(settings=WebDiscoverySettings(enabled=True, api_key=""))
    assert status == dry_run.NOT_RUNNABLE_EXIT
    assert "TAVILY_API_KEY" in capsys.readouterr().out


def candidate(url: str, domain: str, **kwargs) -> DiscoveryCandidate:
    """A selected candidate, as the real run leaves one."""
    values = {
        "title": "A new robotics lab ships an agent",
        "snippet": AI_SNIPPET,
        "canonical_url": url,
        "matched_queries": ["q0", "q1"],
        "query_ranks": [2, 5],
        "published_at": NOW - timedelta(hours=1),
    }
    values.update(kwargs)
    return DiscoveryCandidate(url=url, domain=domain, **values)


def test_the_dry_run_prints_the_funnel_and_the_final_list(
    capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point of the job: the funnel plus the selected list."""
    from app.jobs import web_discovery_dry_run as dry_run

    monkeypatch.setattr(
        dry_run,
        "collect_web_discovery",
        lambda now, *, settings=None: discovery_outcome(
            candidates=[candidate("https://new-lab.test/news/agent", "new-lab.test")]
        ),
    )
    status = dry_run.run(settings=configured())
    output = capsys.readouterr().out

    assert status == 0
    assert "Web Discovery dry run (read-only)" in output
    assert "Web discovery (Tavily)" in output
    assert "Selected: 1" in output
    assert "Domain distribution: 1 domains in 1 candidates" in output
    assert "New / discovered: 1" in output
    assert "new-lab.test" in output
    assert "VERDICT: candidates found" in output


def test_the_dry_run_reports_an_unusable_provider(
    capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.jobs import web_discovery_dry_run as dry_run

    monkeypatch.setattr(
        dry_run,
        "collect_web_discovery",
        lambda now, *, settings=None: discovery_outcome(
            success=False, error="q0: HTTP 401: the API key was rejected"
        ),
    )
    assert dry_run.run(settings=configured()) == dry_run.NO_CANDIDATES_EXIT
    output = capsys.readouterr().out
    assert "no candidate survived the funnel" in output
    assert "HTTP 401" in output


def test_the_dry_run_never_opens_the_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """Read-only is the job's contract: a dry run must not touch SQLite."""
    from app.jobs import web_discovery_dry_run as dry_run

    def forbidden(*args, **kwargs):
        raise AssertionError("a dry run must not open a database session")

    monkeypatch.setattr("app.db.session.new_session", forbidden)
    monkeypatch.setattr(
        dry_run,
        "collect_web_discovery",
        lambda now, *, settings=None: discovery_outcome(),
    )
    assert dry_run.run(settings=configured()) == dry_run.NO_CANDIDATES_EXIT


def test_the_dry_run_never_enriches_or_extracts(monkeypatch: pytest.MonkeyPatch) -> None:
    """It prints candidates; it does not run the pipeline on them."""
    from app.jobs import web_discovery_dry_run as dry_run

    for target in (
        "app.services.article_extractor.extract_articles",
        "app.services.llm.enrich_articles",
    ):
        module, _, name = target.rpartition(".")
        monkeypatch.setattr(
            f"{module}.{name}", lambda *a, **k: pytest.fail("the dry run must not run the pipeline")
        )
    monkeypatch.setattr(
        dry_run, "collect_web_discovery", lambda now, *, settings=None: discovery_outcome()
    )
    assert dry_run.run(settings=configured()) == dry_run.NO_CANDIDATES_EXIT


def test_the_dry_run_prints_the_configured_limits(
    capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.jobs import web_discovery_dry_run as dry_run

    monkeypatch.setattr(dry_run, "collect_web_discovery", lambda now, *, settings=None: discovery_outcome())
    dry_run.run(settings=configured(max_candidates=7, max_per_domain=1, results_per_query=3))
    output = capsys.readouterr().out
    assert "Max candidates: 7" in output
    assert "Max per domain: 1" in output
    assert "Results per query: 3" in output