from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_get_today_daily() -> None:
    response = client.get("/api/v1/daily")
    assert response.status_code == 200
    payload = response.json()
    assert payload["date"] == "2026-09-10"
    assert payload["title"]
    assert payload["description"]
    assert len(payload["news"]) == 10
    assert len(payload["github_projects"]) >= 1
    first = payload["news"][0]
    assert "title_cn" in first
    assert "why_it_matters" in first


def test_get_daily_by_date() -> None:
    response = client.get("/api/v1/daily/2026-09-09")
    assert response.status_code == 200
    payload = response.json()
    assert payload["date"] == "2026-09-09"
    assert payload["news"]


def test_get_news() -> None:
    response = client.get("/api/v1/news/n-20260910-01")
    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "n-20260910-01"
    assert payload["title_cn"]
    assert payload["url"].startswith("https://")


def test_list_github() -> None:
    response = client.get("/api/v1/github")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert payload
    project = payload[0]
    assert "repo" in project
    assert "stars_delta" in project
    assert "summary_cn" in project


def test_daily_not_found() -> None:
    response = client.get("/api/v1/daily/2019-01-01")
    assert response.status_code == 404
    assert response.json()["detail"] == "Daily digest not found"


def test_news_not_found() -> None:
    response = client.get("/api/v1/news/missing-id")
    assert response.status_code == 404
    assert response.json()["detail"] == "News item not found"
