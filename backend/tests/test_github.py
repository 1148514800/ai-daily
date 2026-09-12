
import json
from pathlib import Path

import httpx
import pytest

from app.collectors.github_trending import parse_trending_html
from app.pipelines.github_filter import ai_relevance_score, is_ai_repo
from app.pipelines.github_normalize import project_from_trending, stable_github_id
from app.services.github_client import GitHubClient, RepoMetadata, is_rate_limit_response
from app.services.github_store import GitHubStore
from app.services.llm.cache import LLMCache
from app.services.llm.client import LLMCompletion, LLMError
from app.services.llm.github_enrich import enrich_github_projects
from app.services.llm.settings import LLMSettings
from tests.conftest import fake_github_metadata, read_fixture


def parsed_repos():
    return parse_trending_html(read_fixture("github_trending.html")).parsed


def enabled_settings(tmp_path: Path) -> LLMSettings:
    return LLMSettings(
        enabled=True,
        api_key="test-key",
        model="test-model",
        base_url="https://example.invalid/v1",
        timeout=20.0,
        cache_dir=tmp_path / "llm-cache",
    )


class FakeLLM:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    def complete(self, messages):
        self.calls += 1
        item = self.outcomes.pop(0)
        if isinstance(item, Exception):
            raise item
        return LLMCompletion(text=str(item), input_tokens=8, output_tokens=12)


def test_parse_trending_repos() -> None:
    result = parse_trending_html(read_fixture("github_trending.html"))
    assert result.success
    assert result.fetched == 6
    repos = {item.repo: item for item in result.parsed}
    assert repos["openai/codex"].name == "codex"
    assert repos["openai/codex"].stars == 18300
    assert repos["openai/codex"].stars_today == 842
    assert repos["openai/codex"].language == "Rust"
    assert repos["openai/codex"].rank == 1


def test_parse_missing_description_and_language() -> None:
    repos = {item.repo: item for item in parsed_repos()}
    item = repos["example/no-meta"]
    assert item.description == ""
    assert item.language == ""
    assert item.stars == 12
    assert item.stars_today is None


def test_transformers_missing_language_on_page() -> None:
    repos = {item.repo: item for item in parsed_repos()}
    assert repos["huggingface/transformers"].language == ""
    assert repos["huggingface/transformers"].stars_today == 190


def test_stable_id() -> None:
    first = stable_github_id("openai/codex")
    assert first == stable_github_id("openai/codex")
    assert first == stable_github_id("OpenAI/Codex")
    assert first.startswith("gh-")
    assert first != stable_github_id("openai/whisper")


def test_ai_keyword_filter() -> None:
    repos = {item.repo: item for item in parsed_repos()}
    assert is_ai_repo(repos["openai/codex"])
    assert is_ai_repo(repos["ggml-org/llama.cpp"])
    assert is_ai_repo(repos["huggingface/transformers"])
    assert not is_ai_repo(repos["vercel/next.js"])
    assert not is_ai_repo(repos["shop/homepage"])
    assert not is_ai_repo(repos["example/no-meta"])
    assert ai_relevance_score(repos["openai/codex"]) >= 2


def test_rank_is_preserved() -> None:
    ranks = [item.rank for item in parsed_repos()]
    assert ranks == sorted(ranks)
    assert parsed_repos()[0].repo == "openai/codex"


def test_project_uses_rest_metadata() -> None:
    raw = parsed_repos()[0]
    metadata = fake_github_metadata("openai", "codex")
    project = project_from_trending(raw, metadata)
    assert project.stars == 18300
    assert project.forks == 1200
    assert project.license == "Apache-2.0"
    assert "ai" in project.topics
    assert project.stars_delta == 842
    assert project.url.startswith("https://github.com/openai/codex")


@pytest.mark.real_github_client
def test_rest_timeout_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args, **kwargs):
        raise httpx.TimeoutException("slow")

    monkeypatch.setattr(httpx.Client, "get", boom)
    client = GitHubClient(token="")
    assert client.get_repo("openai", "codex") is None


@pytest.mark.real_github_client
def test_rate_limit_stops_batch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"message": "API rate limit exceeded"},
            headers={
                "x-ratelimit-limit": "60",
                "x-ratelimit-remaining": "0",
                "x-ratelimit-reset": "1",
            },
            request=request,
        )

    client = GitHubClient(token="", transport=httpx.MockTransport(handler))
    assert client.get_repo("openai", "codex") is None
    assert client.rate_limited is True
    assert client.get_repo("ggml-org", "llama.cpp") is None


def test_rate_limit_helper() -> None:
    response = httpx.Response(
        429,
        json={"message": "rate limit"},
        headers={"x-ratelimit-remaining": "0"},
    )
    assert is_rate_limit_response(response)


@pytest.mark.real_github_client
def test_no_token_omits_authorization() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={"stargazers_count": 10, "forks_count": 1, "language": "Go", "topics": []},
            headers={"x-ratelimit-remaining": "50", "x-ratelimit-limit": "60"},
            request=request,
        )

    client = GitHubClient(token="", transport=httpx.MockTransport(handler))
    meta = client.get_repo("openai", "codex")
    assert captured["auth"] is None
    assert meta is not None
    assert meta.stars == 10


@pytest.mark.real_github_client
def test_token_sets_authorization() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={"stargazers_count": 10, "forks_count": 1, "topics": ["llm"]},
            headers={"x-ratelimit-remaining": "4999", "x-ratelimit-limit": "5000"},
            request=request,
        )

    client = GitHubClient(token="secret-token", transport=httpx.MockTransport(handler))
    client.get_repo("openai", "codex")
    assert captured["auth"] == "Bearer secret-token"


def test_store_filters_and_keeps_rank() -> None:
    store = GitHubStore()
    stats = store.refresh()
    repos = [item.repo for item in store.list_projects()]
    assert repos == ["openai/codex", "ggml-org/llama.cpp", "huggingface/transformers"]
    assert [item.rank for item in store.list_projects()] == [1, 3, 5]
    assert stats.ai_candidates == 3
    assert stats.selected == 3
    assert store.list_projects()[2].language == "Python"


def test_llm_disabled_fallback(tmp_path: Path) -> None:
    store = GitHubStore()
    store.refresh()
    project = store.list_projects()[0]
    assert project.summary_cn
    assert project.why_it_matters == ""


def test_github_enrichment_success(tmp_path: Path) -> None:
    store = GitHubStore()
    store.refresh()
    client = FakeLLM([json.dumps({"summary_cn": "用于仓库内编程的编码代理。", "why_it_matters": "今日新增超过 800 Star。"})])
    items, stats = enrich_github_projects(
        store.list_projects()[:1],
        settings=enabled_settings(tmp_path),
        cache=LLMCache(tmp_path / "llm-cache"),
        client=client,
    )
    assert stats.success == 1
    assert items[0].summary_cn == "用于仓库内编程的编码代理。"
    assert "800" in items[0].why_it_matters


def test_github_enrichment_failure_fallback(tmp_path: Path) -> None:
    store = GitHubStore()
    store.refresh()
    original = store.list_projects()[0]
    client = FakeLLM([LLMError("timeout"), LLMError("timeout")])
    items, stats = enrich_github_projects(
        [original],
        settings=enabled_settings(tmp_path),
        cache=LLMCache(tmp_path / "llm-cache"),
        client=client,
    )
    assert stats.fallback == 1
    assert items[0].summary_cn == original.description
    assert items[0].why_it_matters == ""


def test_github_cache_hit(tmp_path: Path) -> None:
    store = GitHubStore()
    store.refresh()
    cache = LLMCache(tmp_path / "llm-cache")
    settings = enabled_settings(tmp_path)
    enrich_github_projects(
        store.list_projects()[:1],
        settings=settings,
        cache=cache,
        client=FakeLLM([json.dumps({"summary_cn": "缓存摘要", "why_it_matters": ""})]),
    )
    second = FakeLLM([json.dumps({"summary_cn": "不应使用", "why_it_matters": ""})])
    items, stats = enrich_github_projects(
        store.list_projects()[:1],
        settings=settings,
        cache=cache,
        client=second,
    )
    assert second.calls == 0
    assert stats.cache_hits == 1
    assert items[0].summary_cn == "缓存摘要"


def test_trending_failure_returns_empty_then_keeps_previous() -> None:
    store = GitHubStore()
    store.refresh()
    assert store.list_projects()
    previous = store.list_projects()

    def boom(url: str, timeout: float = 15.0) -> str:
        raise httpx.ConnectError("offline")

    stats = store.refresh(fetch_text=boom)
    assert stats.used_previous is True
    assert store.list_projects() == previous

    empty = GitHubStore()
    empty.refresh(fetch_text=boom)
    assert empty.list_projects() == []


def test_github_api_contract(client) -> None:
    response = client.get("/api/v1/github")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert payload
    first = payload[0]
    for key in ("id", "repo", "name", "description", "language", "stars", "stars_delta", "summary_cn", "why_it_matters", "url"):
        assert key in first
    assert first["repo"] == "openai/codex"
    assert first["stars_delta"] == 842
    repos = [item["repo"] for item in payload]
    assert "vercel/next.js" not in repos
