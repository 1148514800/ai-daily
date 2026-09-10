from datetime import datetime, timezone

from app.collectors.openai import collect_openai_news, within_last_hours
from app.models import DailyDigest, NewsItem


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def empty_digest(date: str) -> DailyDigest:
    return DailyDigest(
        date=date,
        title="今日 AI 日报",
        description="今天还没有新的 OpenAI 资讯。",
        news=[],
        github_projects=[],
    )


class DigestStore:
    def __init__(self) -> None:
        self.digest: DailyDigest | None = None
        self.news_by_id: dict[str, NewsItem] = {}
        self.last_error: str | None = None

    def refresh(self, now: datetime | None = None, fetch_text=None) -> None:
        current = now or now_utc()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        date = current.date().isoformat()

        result = collect_openai_news(fetch_text=fetch_text)
        self.last_error = result.error

        recent = [item for item in result.news_items if within_last_hours(item, current)]
        recent.sort(key=lambda item: item.published_at, reverse=True)

        if recent:
            description = f"来自 OpenAI News 的 {len(recent)} 条更新。"
        else:
            description = "今天还没有新的 OpenAI 资讯。"

        self.news_by_id = {item.id: item for item in result.news_items}
        self.digest = DailyDigest(
            date=date,
            title="今日 AI 日报",
            description=description,
            news=recent,
            github_projects=[],
        )

    def get_today(self) -> DailyDigest:
        if self.digest is None:
            return empty_digest(now_utc().date().isoformat())
        return self.digest

    def get_by_date(self, date: str) -> DailyDigest | None:
        digest = self.get_today()
        if digest.date == date:
            return digest
        return None

    def get_news(self, news_id: str) -> NewsItem | None:
        return self.news_by_id.get(news_id)


store = DigestStore()
