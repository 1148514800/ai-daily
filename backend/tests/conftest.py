from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FROZEN_NOW = datetime(2026, 9, 10, 20, 0, tzinfo=timezone.utc)
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "openai_news.xml"


@pytest.fixture
def openai_rss_xml() -> str:
    return FIXTURE_PATH.read_text(encoding="utf-8")


@pytest.fixture
def patch_openai_rss(monkeypatch: pytest.MonkeyPatch, openai_rss_xml: str):
    monkeypatch.setattr(
        "app.collectors.openai.fetch_rss_text",
        lambda url, timeout=10.0: openai_rss_xml,
    )
    monkeypatch.setattr("app.services.digest_store.now_utc", lambda: FROZEN_NOW)
    return openai_rss_xml


@pytest.fixture
def client(patch_openai_rss):
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
