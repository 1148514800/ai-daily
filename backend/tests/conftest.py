from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.db.session import configure_database, init_db, reset_database
from app.services.github_client import RepoMetadata

# 2026-09-10 20:00 UTC is 2026-09-11 04:00 in Asia/Shanghai, which keeps the
# 24h collector window stable while exercising timezone-aware digest dates.
FROZEN_NOW = datetime(2026, 9, 10, 20, 0, tzinfo=timezone.utc)
FROZEN_DIGEST_DATE = "2026-09-11"
FIXTURES = Path(__file__).parent / "fixtures"


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def openai_rss_xml() -> str:
    return read_fixture("openai_news.xml")


@pytest.fixture
def deepmind_rss_xml() -> str:
    return read_fixture("deepmind_blog.xml")


@pytest.fixture
def huggingface_rss_xml() -> str:
    return read_fixture("huggingface_blog.xml")


@pytest.fixture
def github_trending_html() -> str:
    return read_fixture("github_trending.html")


def make_fixture_fetch(openai_xml: str, deepmind_xml: str, huggingface_xml: str, failing: set[str] | None = None):
    failing = failing or set()

    def fetch(url: str, timeout: float = 10.0) -> str:
        if "openai.com" in url:
            source_id = "openai"
            xml = openai_xml
        elif "deepmind.google" in url:
            source_id = "deepmind"
            xml = deepmind_xml
        elif "huggingface.co" in url:
            source_id = "huggingface"
            xml = huggingface_xml
        else:
            raise httpx.ConnectError(f"unknown source {url}")
        if source_id in failing:
            raise httpx.ConnectError(f"{source_id} offline")
        return xml

    return fetch


def fake_github_metadata(owner: str, name: str) -> RepoMetadata | None:
    catalog = {
        ("openai", "codex"): RepoMetadata(
            stars=18300,
            forks=1200,
            language="Rust",
            license="Apache-2.0",
            topics=("ai", "agents"),
            description="Codex agent",
        ),
        ("ggml-org", "llama.cpp"): RepoMetadata(
            stars=87240,
            forks=9000,
            language="C++",
            license="MIT",
            topics=("llm", "inference"),
            description="LLM inference in C/C++",
        ),
        ("huggingface", "transformers"): RepoMetadata(
            stars=152300,
            forks=31000,
            language="Python",
            license="Apache-2.0",
            topics=("machine-learning", "transformer"),
            description="Transformers",
        ),
        ("vercel", "next.js"): RepoMetadata(
            stars=132000,
            forks=28000,
            language="JavaScript",
            license="MIT",
            topics=("nextjs", "react"),
            description="The React Framework",
        ),
    }
    return catalog.get((owner, name), RepoMetadata(stars=1, forks=0, language="", license="", topics=(), description=""))


@pytest.fixture(autouse=True)
def use_temp_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Every test runs against a throwaway SQLite file, never the real one."""
    db_path = tmp_path / "test_ai_daily.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    configure_database(f"sqlite:///{db_path.as_posix()}")
    init_db()
    yield
    reset_database()


@pytest.fixture(autouse=True)
def disable_llm_by_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("LLM_ENABLED", "false")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path / "llm-cache"))
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)


@pytest.fixture(autouse=True)
def patch_github_network(request, monkeypatch: pytest.MonkeyPatch, github_trending_html: str):
    from app.services.github_store import github_store

    github_store.projects = []
    github_store.last_error = None
    monkeypatch.setattr(
        "app.collectors.github_trending.fetch_trending_html",
        lambda **kwargs: github_trending_html,
    )
    if "real_github_client" in request.keywords:
        return

    def fake_get_repo(self, owner: str, name: str):
        return fake_github_metadata(owner, name)

    monkeypatch.setattr("app.services.github_client.GitHubClient.get_repo", fake_get_repo)


@pytest.fixture
def patch_rss_feeds(monkeypatch: pytest.MonkeyPatch, openai_rss_xml: str, deepmind_rss_xml: str, huggingface_rss_xml: str):
    fetch = make_fixture_fetch(openai_rss_xml, deepmind_rss_xml, huggingface_rss_xml)
    monkeypatch.setattr("app.collectors.rss.fetch_rss_text", fetch)
    monkeypatch.setattr("app.services.digest_store.now_utc", lambda: FROZEN_NOW)
    monkeypatch.setattr("app.services.refresh_service.now_utc", lambda: FROZEN_NOW, raising=False)
    return fetch


@pytest.fixture
def client(patch_rss_feeds):
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
