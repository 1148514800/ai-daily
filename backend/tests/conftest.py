from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

FROZEN_NOW = datetime(2026, 9, 10, 20, 0, tzinfo=timezone.utc)
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


@pytest.fixture(autouse=True)
def disable_llm_by_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("LLM_ENABLED", "false")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path / "llm-cache"))


@pytest.fixture
def patch_rss_feeds(monkeypatch: pytest.MonkeyPatch, openai_rss_xml: str, deepmind_rss_xml: str, huggingface_rss_xml: str):
    fetch = make_fixture_fetch(openai_rss_xml, deepmind_rss_xml, huggingface_rss_xml)
    monkeypatch.setattr("app.collectors.rss.fetch_rss_text", fetch)
    monkeypatch.setattr("app.services.digest_store.now_utc", lambda: FROZEN_NOW)
    return fetch


@pytest.fixture
def client(patch_rss_feeds):
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
