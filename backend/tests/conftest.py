from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config.timezone import app_timezone
from app.config.sources import enabled_sources
from app.db.session import configure_database, init_db, reset_database
from app.services.github_client import RepoMetadata

# 2026-09-10 20:00 UTC is 2026-09-11 04:00 in Asia/Shanghai. The fixture feeds
# in this directory publish just after 2026-09-11 00:00 Asia/Shanghai, so they
# are both inside the 24h window and on the same local calendar day as the
# digest date below.
FROZEN_NOW = datetime(2026, 9, 10, 20, 0, tzinfo=timezone.utc)
FROZEN_DIGEST_DATE = "2026-09-11"
FIXTURES = Path(__file__).parent / "fixtures"


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def build_rss(items: list[tuple[str, str, datetime]]) -> str:
    """Build a minimal RSS feed from (title, url, published_at) tuples.

    Date-boundary tests state their publish times explicitly instead of
    mutating a shared fixture, so each case reads as the scenario it checks.
    """
    entries = "\n".join(
        f"    <item>\n"
        f"      <title>{title}</title>\n"
        f"      <link>{url}</link>\n"
        f"      <guid isPermaLink=\"true\">{url}</guid>\n"
        f"      <pubDate>{format_datetime(published)}</pubDate>\n"
        f"    </item>"
        for title, url, published in items
    )
    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        "<rss version=\"2.0\">\n"
        "  <channel>\n"
        "    <title>Test Feed</title>\n"
        "    <link>https://openai.com/news</link>\n"
        f"{entries}\n"
        "  </channel>\n"
        "</rss>\n"
    )


def utc_on_local_day(local_date: str, hour: int = 1) -> datetime:
    """The UTC instant for ``hour`` on a date in APP_TIMEZONE."""
    local = datetime.strptime(local_date, "%Y-%m-%d").replace(hour=hour, tzinfo=app_timezone())
    return local.astimezone(timezone.utc)


def day_feeds(local_date: str, *, hour: int = 1) -> tuple[str, str, str]:
    """Three source feeds whose articles publish on one APP_TIMEZONE day.

    Used by adjacent-day tests: each day has its own URLs, so the two days
    produce genuinely different news_ids and any overlap is a real defect.
    """
    stamp = utc_on_local_day(local_date, hour)
    slug = local_date.replace("-", "")
    openai = build_rss(
        [
            (
                f"OpenAI story {local_date}",
                f"https://openai.com/index/{slug}-openai",
                stamp,
            )
        ]
    )
    deepmind = build_rss(
        [
            (
                f"DeepMind story {local_date}",
                f"https://deepmind.google/blog/{slug}-deepmind",
                stamp,
            )
        ]
    )
    huggingface = build_rss(
        [
            (
                f"Hugging Face story {local_date}",
                f"https://huggingface.co/blog/{slug}-hf",
                stamp,
            )
        ]
    )
    return openai, deepmind, huggingface


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


@pytest.fixture
def anthropic_news_html() -> str:
    return read_fixture("anthropic_news.html")


@pytest.fixture
def deepseek_index_html() -> str:
    return read_fixture("deepseek_index.html")


@pytest.fixture
def deepseek_news_html() -> str:
    return read_fixture("deepseek_news.html")


@pytest.fixture
def kimi_blog_html() -> str:
    return read_fixture("kimi_blog.html")


@pytest.fixture
def nvidia_rss_xml() -> str:
    return read_fixture("nvidia_blog.xml")


@pytest.fixture
def qwen_rss_xml() -> str:
    return read_fixture("qwen_blog.xml")


@pytest.fixture
def techcrunch_rss_xml() -> str:
    return read_fixture("techcrunch_ai.xml")


@pytest.fixture
def qbitai_rss_xml() -> str:
    return read_fixture("qbitai.xml")


EMPTY_RSS = (
    "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
    "<rss version=\"2.0\"><channel><title>Empty</title></channel></rss>\n"
)

# Pages that load but list nothing, so an unmapped source still succeeds with
# zero news instead of failing. Each keeps whichever structure its extractor
# insists on, which is what tells "nothing published" apart from "markup moved".
EMPTY_HTML = {
    "deepseek": (
        "<html><body><a href=\"/news/placeholder\">News</a>"
        "<a class=\"menu__link\" href=\"/news/placeholder\">News</a></body></html>"
    ),
    "anthropic": "<html><body><a href=\"/news/placeholder\">Undated</a></body></html>",
    "kimi": (
        "<html><body><script>self.__next_f.push([1,\"1:[{\\\"articleList\\\":"
        "{\\\"items\\\":[]}}]\\n\"])</script></body></html>"
    ),
}

DEEPSEEK_SOURCE_ID = "deepseek"
DEEPSEEK_URL_PREFIX = "https://api-docs.deepseek.com/"


def empty_page(source_id: str, kind: str) -> str:
    """A payload valid for ``source_id`` that lists nothing.

    Window and dedupe tests only care about the sources they configure, so the
    rest answer with an empty page of the right shape: an empty feed for RSS,
    an empty listing for HTML. That keeps every source succeeding instead of
    failing on a format it never sees in production.
    """
    if kind != "html":
        return EMPTY_RSS
    return EMPTY_HTML.get(source_id, f"<html><body><p>{source_id}</p></body></html>")


def source_payloads(openai_xml: str, deepmind_xml: str, huggingface_xml: str) -> dict[str, str]:
    """Fixture payload keyed by source id, with an empty page for the rest."""
    payloads = {"openai": openai_xml, "deepmind": deepmind_xml, "huggingface": huggingface_xml}
    for source in enabled_sources():
        payloads.setdefault(source.id, empty_page(source.id, source.kind))
    return payloads


def make_fixture_fetch(
    openai_xml: str,
    deepmind_xml: str,
    huggingface_xml: str,
    failing: set[str] | None = None,
    pages: dict[str, str] | None = None,
):
    """Serve the configured fixture for every enabled source URL.

    A source without an explicit payload answers with an empty fixture, so a
    test that only cares about three sources never trips over the other enabled
    ones. ``failing`` makes a named source raise, which is how the
    per-source-failure tests stay deterministic without touching the network.
    ``pages`` adds extra ``{url: payload}`` routes for sources that read more
    than one page, such as DeepSeek's index-then-listing pair.
    """
    failing = failing or set()
    fixtures = source_payloads(openai_xml, deepmind_xml, huggingface_xml)
    routes: dict[str, tuple[str, str]] = {
        source.url: (source.id, fixtures[source.id]) for source in enabled_sources()
    }
    for url, payload in (pages or {}).items():
        source_id = DEEPSEEK_SOURCE_ID if url.startswith(DEEPSEEK_URL_PREFIX) else url
        routes[url] = (source_id, payload)

    def fetch(url: str, timeout: float = 10.0) -> str:
        route = routes.get(url) or routes.get(url.rstrip("/")) or routes.get(url + "/")
        if route is None and url.startswith(DEEPSEEK_URL_PREFIX):
            # DeepSeek reads its release listing from a second page whose URL is
            # only known after the index is parsed, so every further DeepSeek URL
            # serves the same listing fixture.
            route = (DEEPSEEK_SOURCE_ID, fixtures.get(DEEPSEEK_SOURCE_ID, EMPTY_RSS))
        if route is None:
            raise httpx.ConnectError(f"unknown source {url}")
        source_id, payload = route
        if source_id in failing:
            raise httpx.ConnectError(f"{source_id} offline")
        return payload

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
def disable_scheduler_by_default(monkeypatch: pytest.MonkeyPatch):
    """Tests drive refreshes explicitly instead of waiting for real clock time."""
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("DAILY_REFRESH_HOUR", "8")
    monkeypatch.setenv("DAILY_REFRESH_MINUTE", "0")
    monkeypatch.setenv("APP_TIMEZONE", "Asia/Shanghai")


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
    # HTML sources go through their own fetch function, so patching only the RSS
    # one would let the Anthropic / DeepSeek / Kimi tests reach the network.
    monkeypatch.setattr("app.collectors.html.fetch_html", fetch)
    monkeypatch.setattr("app.services.digest_store.now_utc", lambda: FROZEN_NOW)
    monkeypatch.setattr("app.services.refresh_service.now_utc", lambda: FROZEN_NOW, raising=False)
    return fetch


@pytest.fixture
def client(patch_rss_feeds):
    """API client backed by a database refreshed exactly once at fixture setup."""
    from app.main import app
    from app.services.refresh_service import refresh_all

    refresh_all(now=FROZEN_NOW)
    with TestClient(app) as test_client:
        yield test_client
