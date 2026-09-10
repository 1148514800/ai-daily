from app.data.github import GITHUB_BY_ID, GITHUB_PROJECTS
from app.data.news import NEWS_BY_ID
from app.models import DailyDigest, GitHubProject, NewsItem

TODAY_DATE = "2026-09-10"

def _news(ids: list[str]) -> list[NewsItem]:
    return [NEWS_BY_ID[item_id] for item_id in ids]


def _github(ids: list[str]) -> list[GitHubProject]:
    return [GITHUB_BY_ID[item_id] for item_id in ids]


DIGESTS: list[DailyDigest] = [
    DailyDigest(
        date="2026-09-10",
        title="今日 AI 日报",
        description="评测可复现、端侧长上下文，以及更适合资讯流水线的开源工具。",
        news=_news([
            "n-20260910-01",
            "n-20260910-02",
            "n-20260910-03",
            "n-20260910-04",
            "n-20260910-05",
            "n-20260910-06",
            "n-20260910-07",
            "n-20260910-08",
            "n-20260910-09",
            "n-20260910-10",
        ]),
        github_projects=GITHUB_PROJECTS,
    ),
    DailyDigest(
        date="2026-09-09",
        title="昨日 AI 日报",
        description="截图补丁、Agent 证据链，以及本地长文本处理。",
        news=_news(["n-20260909-01", "n-20260909-02", "n-20260909-03"]),
        github_projects=_github(["gh-mlx-lm"]),
    ),
    DailyDigest(
        date="2026-09-08",
        title="9月8日 AI 日报",
        description="引用要到页码，轻量 reranker 也能提升旧闻查找。",
        news=_news(["n-20260908-01", "n-20260908-02"]),
        github_projects=_github(["gh-rerankers"]),
    ),
    DailyDigest(
        date="2026-09-07",
        title="9月7日 AI 日报",
        description="论文 OCR 更稳，模型发布开始认真对待许可证。",
        news=_news(["n-20260907-01", "n-20260907-02"]),
        github_projects=[],
    ),
]

DIGESTS_BY_DATE = {item.date: item for item in DIGESTS}
