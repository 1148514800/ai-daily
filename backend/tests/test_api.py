from app.pipelines.normalize import stable_news_id
from tests.conftest import FROZEN_DIGEST_DATE


def test_health(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_get_today_daily(client) -> None:
    response = client.get("/api/v1/daily")
    assert response.status_code == 200
    payload = response.json()
    assert payload["date"] == FROZEN_DIGEST_DATE
    assert payload["title"]
    assert payload["description"]
    sources = {item["source"] for item in payload["news"]}
    assert sources == {"OpenAI", "Google DeepMind", "Hugging Face"}
    assert len(payload["news"]) == 6
    first = payload["news"][0]
    assert first["why_it_matters"] == ""
    assert first["title_cn"] == first["title_original"]


def test_get_daily_by_date(client) -> None:
    response = client.get(f"/api/v1/daily/{FROZEN_DIGEST_DATE}")
    assert response.status_code == 200
    assert response.json()["date"] == FROZEN_DIGEST_DATE


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


def test_list_github_by_date(client) -> None:
    response = client.get(f"/api/v1/github?date={FROZEN_DIGEST_DATE}")
    assert response.status_code == 200
    payload = response.json()
    assert [item["repo"] for item in payload] == ["openai/codex", "ggml-org/llama.cpp", "huggingface/transformers"]


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
    monkeypatch.setattr(
        "app.services.refresh_service.now_utc",
        lambda: datetime(2026, 9, 10, 20, tzinfo=timezone.utc),
    )

    with TestClient(app) as test_client:
        response = test_client.get("/api/v1/daily")
        assert response.status_code == 200
        assert response.json()["news"] == []


def test_daily_keeps_importance_score_optional(client) -> None:
    payload = client.get('/api/v1/daily').json()
    first = payload['news'][0]
    assert 'id' in first
    assert 'title_cn' in first
    assert 'title_original' in first
    assert 'summary' in first
    assert 'why_it_matters' in first
    assert 'importance_score' in first
    assert first['importance_score'] is None


def test_list_digests(client) -> None:
    response = client.get("/api/v1/digests")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    summary = payload[0]
    assert summary == {
        "date": FROZEN_DIGEST_DATE,
        "title": "今日 AI 日报",
        "news_count": 6,
        "github_count": 3,
    }



def test_favorites_flow(client) -> None:
    news_id = stable_news_id("https://openai.com/index/gpt-6-astra")
    created = client.post("/api/v1/favorites", json={"item_type": "news", "item_id": news_id})
    assert created.status_code == 201
    favorite = created.json()
    assert favorite["item_type"] == "news"
    assert favorite["item"]["id"] == news_id

    # Duplicate favorites return the existing row instead of creating another.
    duplicate = client.post("/api/v1/favorites", json={"item_type": "news", "item_id": news_id})
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == favorite["id"]

    listed = client.get("/api/v1/favorites")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [favorite["id"]]

    deleted = client.delete(f"/api/v1/favorites/{favorite['id']}")
    assert deleted.status_code == 204
    assert client.get("/api/v1/favorites").json() == []


def test_favorite_github(client) -> None:
    response = client.post("/api/v1/favorites", json={"item_type": "github", "item_id": "gh-x"})
    assert response.status_code == 404
    payload = client.get("/api/v1/github").json()
    created = client.post("/api/v1/favorites", json={"item_type": "github", "item_id": payload[0]["id"]})
    assert created.status_code == 201
    assert created.json()["item_type"] == "github"
    assert created.json()["item"]["repo"] == "openai/codex"


def test_favorite_invalid_target(client) -> None:
    assert client.post("/api/v1/favorites", json={"item_type": "news", "item_id": "nope"}).status_code == 404
    assert client.post("/api/v1/favorites", json={"item_type": "movie", "item_id": "x"}).status_code == 400


def test_delete_missing_favorite(client) -> None:
    assert client.delete("/api/v1/favorites/9999").status_code == 404
