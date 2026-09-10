from app.pipelines.normalize import stable_news_id


def test_health(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_get_today_daily(client) -> None:
    response = client.get("/api/v1/daily")
    assert response.status_code == 200
    payload = response.json()
    assert payload["date"] == "2026-09-10"
    assert payload["title"]
    assert payload["description"]
    sources = {item["source"] for item in payload["news"]}
    assert sources == {"OpenAI", "Google DeepMind", "Hugging Face"}
    assert len(payload["news"]) == 6
    first = payload["news"][0]
    assert first["why_it_matters"] == ""
    assert first["title_cn"] == first["title_original"]


def test_get_daily_by_date(client) -> None:
    response = client.get("/api/v1/daily/2026-09-10")
    assert response.status_code == 200
    assert response.json()["date"] == "2026-09-10"


def test_get_news(client) -> None:
    news_id = stable_news_id("https://openai.com/index/gpt-6-astra")
    response = client.get(f"/api/v1/news/{news_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == news_id
    assert payload["url"] == "https://openai.com/index/gpt-6-astra"
    assert payload["source"] == "OpenAI"


def test_list_github(client) -> None:
    response = client.get("/api/v1/github")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert payload
    project = payload[0]
    assert "repo" in project
    assert "stars_delta" in project
    assert "summary_cn" in project


def test_daily_not_found(client) -> None:
    response = client.get("/api/v1/daily/2019-01-01")
    assert response.status_code == 404
    assert response.json()["detail"] == "Daily digest not found"


def test_news_not_found(client) -> None:
    response = client.get("/api/v1/news/missing-id")
    assert response.status_code == 404
    assert response.json()["detail"] == "News item not found"


def test_daily_ok_when_refresh_fails(monkeypatch) -> None:
    from datetime import datetime, timezone

    from fastapi.testclient import TestClient

    from app.collectors.rss import CollectResult
    from app.main import app

    monkeypatch.setattr(
        "app.services.digest_store.collect_all_sources",
        lambda **kwargs: [
            CollectResult(source_id="openai", source_name="OpenAI", success=False, error="offline"),
            CollectResult(source_id="deepmind", source_name="Google DeepMind", success=False, error="offline"),
            CollectResult(source_id="huggingface", source_name="Hugging Face", success=False, error="offline"),
        ],
    )
    monkeypatch.setattr(
        "app.services.digest_store.now_utc",
        lambda: datetime(2026, 9, 10, 20, tzinfo=timezone.utc),
    )

    with TestClient(app) as test_client:
        response = test_client.get("/api/v1/daily")
        assert response.status_code == 200
        assert response.json()["news"] == []
