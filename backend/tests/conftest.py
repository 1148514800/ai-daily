from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
import os

# Set before anything under ``app`` is imported. ``load_dotenv`` never overrides
# a variable that is already set, so this also wins over a development ``.env``:
# the whole process is a test process, and every ``APP_ENV`` read agrees.
os.environ["APP_ENV"] = "test"

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config.database_safety import DEFAULT_DATABASE_FILE, is_default_database
from app.config.environment import APP_ENV_TEST, app_env
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
def mistral_rss_xml() -> str:
    return read_fixture("mistral_blog.xml")


@pytest.fixture
def microsoft_research_rss_xml() -> str:
    return read_fixture("microsoft_research.xml")


@pytest.fixture
def ars_technica_rss_xml() -> str:
    return read_fixture("ars_technica_ai.xml")


@pytest.fixture
def cohere_blog_html() -> str:
    return read_fixture("cohere_blog.html")


@pytest.fixture
def cursor_blog_html() -> str:
    return read_fixture("cursor_blog.html")


EMPTY_RSS = (
    "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
    "<rss version=\"2.0\"><channel><title>Empty</title></channel></rss>\n"
)


def stored_body(session, news_id: str) -> str:
    """The original body of a stored article.

    Since Phase 10.11 the body is not part of any list or detail payload, so it
    has to be read explicitly through the repository's content accessor. Tests
    that only care about the text use this instead of ``get_detail``.
    """
    from app.db.repositories import NewsRepository

    content = NewsRepository(session).get_content(news_id)
    return content.content_original if content is not None else ""


def api_body(client, news_id: str) -> str:
    """The original body as the API returns it, from the content endpoint."""
    response = client.get(f"/api/v1/news/{news_id}/content")
    assert response.status_code == 200, response.text
    return response.json()["content_original"]

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
    # Both are listing pages whose card markup is present but carries no dated
    # entry, so the extractor returns zero news instead of reporting a change.
    "cohere": (
        "<html><body><a href=\"/blog/placeholder\">Placeholder</a>"
        "<p>No posts yet.</p></body></html>"
    ),
    "cursor": (
        "<html><body><div class=\"blog-directory card-border\">"
        "<a class=\"blog-directory__row\" href=\"/blog/placeholder\">Placeholder</a>"
        "</div></body></html>"
    ),
    # Phase 10.13's four HTML sources. Each keeps the exact structure its own
    # extractor insists on, because an extractor that cannot find its marker
    # reports a changed page: a source that is merely unpublished has to be
    # distinguishable from one whose markup moved.
    "bytedance-seed": (
        "<html><body><script>window._ROUTER_DATA = "
        "{\"loaderData\": {\"(locale$)/blog/page\": {\"article_list\": [], "
        "\"has_more\": false, \"total\": 0}}}</script></body></html>"
    ),
    "tencent-hunyuan": (
        "{\"code\": 0, \"msg\": \"success\", \"data\": {\"totalNum\": 0, \"list\": []}}"
    ),
    "zhipu-glm": (
        "<html><body><script>self.__next_f.push([1,\"19:[\\\"$\\\",\\\"$L16\\\",null,"
        "{\\\"newsItems\\\":[]}]]\\n\"])</script></body></html>"
    ),
    # A listing link with no date: the extractor returns zero entries rather
    # than reporting the page as changed.
    "minimax": "<html><body><a href=\"/blog/placeholder\"><h3>Placeholder</h3></a></body></html>",
    # Phase 10.14's additional channels. Each keeps the structure its extractor
    # insists on while listing nothing, so an unpublished channel succeeds with
    # zero news instead of looking like a broken page.
    "anthropic-research": (
        "<html><body><a href=\"/research/placeholder\"><h3>Placeholder</h3></a>"
        "<a href=\"/research/team/alignment\">Team</a></body></html>"
    ),
    "anthropic-engineering": (
        "<html><body><a href=\"/engineering/placeholder\"><h3>Placeholder</h3></a></body></html>"
    ),
    "cursor-changelog": (
        "<html><body><article><a href=\"/changelog/placeholder\"><h1>Placeholder</h1></a>"
        "</article></body></html>"
    ),
    "cohere-research": (
        "<html><body><a href=\"/research/papers/placeholder\"><h3>Placeholder</h3></a></body></html>"
    ),
    "tencent-cloud-ai": (
        "<html><body><div class=\"msg-list-item\"><div class=\"msg-list-con\">"
        "<a href=\"/announce/detail/0\">Placeholder</a></div>"
        "<div class=\"msg-list-aside\"><span>Not a date</span></div></div></body></html>"
    ),
    "tencent-workbuddy": (
        "<html><body><div class=\"vp-doc\"><h2>1.0.0 版本发布</h2>"
        "<ul><li>Placeholder</li></ul></div></body></html>"
    ),
    "meta-ai-blog": (
        "<html><body><div><a href=\"/blog/placeholder/\"><h4>Placeholder</h4></a>"
        "<div class=\"_amdj\">No date yet</div></div></body></html>"
    ),
    "alibaba-model-studio": (
        "<html><body><table><tr><th>模型类型</th><th>时间</th><th>模型 ID</th><th>功能说明</th></tr>"
        "<tr><td>占位</td><td>待定</td><td>placeholder-model</td><td>占位说明</td></tr>"
        "</table></body></html>"
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


def _assert_not_the_production_database(url: str) -> None:
    """Refuse to run a test against the real database, loudly.

    The whole suite exists to prove behaviour without touching production data,
    so pointing it at ``backend/data/ai_daily.db`` is a defect in the test setup,
    not a test failure to interpret: it fails with the reason spelled out. The
    connection layer enforces the same rule, so this is the readable first line
    of defence rather than the only one.
    """
    if is_default_database(url):
        raise RuntimeError(
            "tests must not use the production database "
            f"({DEFAULT_DATABASE_FILE}); got DATABASE_URL={url!r}"
        )


@pytest.fixture
def fake_default_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Repoint the production-database sentinel at a temporary file.

    A few tests need to exercise the real guard path - refuse, then ``validate ->
    backup -> execute`` with ``--allow-production``. They cannot use the actual
    default file, so the sentinel itself is redirected. The production code is
    unchanged and fully exercised; only the file it considers production differs.
    """
    from app.config import database_safety

    fake = tmp_path / "fake_production.db"
    monkeypatch.setattr(database_safety, "DEFAULT_DATABASE_FILE", fake)
    # Re-check what the guard compares against, so a broken patch fails loudly.
    assert database_safety.is_default_database(f"sqlite:///{fake.as_posix()}")
    return fake


@pytest.fixture(autouse=True)
def use_temp_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Every test runs against a throwaway SQLite file, never the real one."""
    db_path = tmp_path / "test_ai_daily.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("APP_ENV", APP_ENV_TEST)
    monkeypatch.setenv("DATABASE_URL", url)
    configure_database(url)
    # Checked after configuring, so a test that overrides the URL itself is held
    # to the same rule as the fixture. Asserted before the test body so a test
    # that deliberately switches APP_ENV is still allowed to do so.
    _assert_not_the_production_database(url)
    assert app_env() == APP_ENV_TEST
    init_db()
    yield
    reset_database()


@pytest.fixture(scope="session", autouse=True)
def production_database_untouched():
    """The whole run must leave the real database byte-identical.

    Session-scoped and unconditional, because this is the one guarantee the test
    suite makes about the machine it runs on. It is what turns "tests point
    somewhere else" from a convention into something the run itself verifies.
    """
    from app.db import readonly

    if not DEFAULT_DATABASE_FILE.exists():
        yield
        return
    before = readonly.file_sha256(DEFAULT_DATABASE_FILE)
    yield
    after = readonly.file_sha256(DEFAULT_DATABASE_FILE)
    assert after == before, (
        "the test suite modified the production database "
        f"({DEFAULT_DATABASE_FILE}); a test is not isolated"
    )


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
def offline_article_pages(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """No test reaches the network for an article body.

    Article extraction runs inside the production refresh path, so without this
    every suite that collects news would fetch the fixture URLs for real. The
    default is a deterministic failure, which is also the documented behaviour
    when a page cannot be read: the article keeps its RSS summary. Tests that
    cover page extraction inject their own ``fetch_page`` / ``fetch`` instead.
    """
    from app.collectors.http import FetchError

    monkeypatch.setenv("ARTICLE_CACHE_DIR", str(tmp_path / "article-cache"))

    def offline(url: str, *, timeout: float = 10.0):
        raise FetchError("article pages are offline in tests")

    monkeypatch.setattr("app.services.article_extractor.fetch_article_page", offline)


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
    # 腾讯混元's listing is a POST-only JSON endpoint rather than a page, so it
    # has its own fetcher; without this one the suite would reach the network
    # for that source alone and collect live articles into the fixtures.
    monkeypatch.setattr("app.collectors.html.fetch_hunyuan_listing", fetch)
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
