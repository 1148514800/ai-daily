"""Phase 10.14: a company is not one source.

Phase 10.13 assumed one official entry point per vendor, which silently lost any
announcement published on a company's *other* official surface: an Anthropic
essay on ``/institute/`` was never a ``/news/`` link, and Tencent WorkBuddy is a
Tencent Cloud product rather than a Hunyuan model post.

This module pins the three things the phase is actually about:

* every source declares which company publishes it and which of that company's
  official channels it is, with ``channel`` kept strictly separate from
  ``source_type``;
* a company's channels are collected independently, so one broken channel
  cannot take the others down, and a wide channel is AI-filtered;
* the named regressions stay fixed: Anthropic's non-``/news/`` paths are
  reachable, and 腾讯云 is a different channel from 腾讯混元.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.collectors.html import (
    PageStructureError,
    alibaba_model_entries,
    anthropic_engineering_entries,
    anthropic_entries,
    anthropic_research_entries,
    collect_html_source,
    cohere_research_entries,
    cursor_changelog_entries,
    meta_ai_entries,
    parse_html_page,
    tencent_cloud_entries,
    tencent_workbuddy_entries,
)
from app.config.sources import (
    NEWS_CHANNELS,
    NEWS_SOURCE_TYPES,
    all_sources,
    enabled_sources,
    organization_map,
    source_by_id,
    unsupported_channels,
)
from app.services.source_health import (
    EMPTY,
    FAIL,
    OK,
    UNSUPPORTED,
    build_coverage,
    build_report,
    format_official_coverage,
)
from tests.conftest import EMPTY_HTML, read_fixture

UTC = timezone.utc

ANTHROPIC_NEWS = read_fixture("anthropic_news.html")
ANTHROPIC_RESEARCH = read_fixture("anthropic_research.html")
ANTHROPIC_ENGINEERING = read_fixture("anthropic_engineering.html")
TENCENT_CLOUD = read_fixture("tencent_cloud_announce.html")
TENCENT_WORKBUDDY = read_fixture("tencent_workbuddy_changelog.html")
META_AI = read_fixture("meta_ai_blog.html")
ALIBABA_MODELS = read_fixture("alibaba_model_studio.html")
COHERE_RESEARCH = read_fixture("cohere_research.html")
CURSOR_CHANGELOG = read_fixture("cursor_changelog.html")

# The channels this phase added, with the company each belongs to.
NEW_CHANNELS = {
    "anthropic-research": ("anthropic", "research"),
    "anthropic-engineering": ("anthropic", "engineering"),
    "cursor-changelog": ("cursor", "changelog"),
    "cohere-research": ("cohere", "research"),
    "nvidia-developer": ("nvidia", "developer"),
    "meta-ai-blog": ("meta", "research"),
    "alibaba-model-studio": ("alibaba", "model"),
    "google-ai": ("google", "product"),
    "google-gemini": ("google", "product"),
    "google-research": ("google", "research"),
    "google-cloud-ai": ("google", "cloud"),
    "tencent-cloud-ai": ("tencent", "cloud"),
    "tencent-workbuddy": ("tencent", "product"),
}


# --- A. source metadata ---


def test_every_source_declares_a_valid_organization_and_channel() -> None:
    for source in all_sources():
        assert source.organization, source.id
        assert source.channel in NEWS_CHANNELS, f"{source.id}: {source.channel}"
        assert source.source_type in NEWS_SOURCE_TYPES, source.id


def test_the_channel_list_is_exactly_the_documented_one() -> None:
    assert set(NEWS_CHANNELS) == {
        "news",
        "research",
        "product",
        "engineering",
        "developer",
        "model",
        "security",
        "changelog",
        "cloud",
    }


def test_channel_is_not_a_source_type() -> None:
    """``source_type`` is trustworthiness; ``channel`` is which surface.

    Anthropic Institute is a ``research`` channel of an ``official`` source, not
    a ``research`` source: it is still Anthropic speaking for itself. Conflating
    the two would drop it out of the official band that dedupe relies on.
    """
    institute = source_by_id("anthropic-research")
    assert institute.source_type == "official"
    assert institute.channel == "research"
    # ``research`` legitimately names both a channel and a source class, which
    # is exactly why the two must not be conflated: the words overlap but the
    # meanings do not. ``official`` and ``media`` are never channels at all.
    assert "official" not in NEWS_CHANNELS
    assert "media" not in NEWS_CHANNELS
    for source in all_sources():
        assert source.channel != "official"
        assert source.channel != "media"


# --- B. organization grouping ---


def test_one_company_is_several_sources() -> None:
    grouped = organization_map()
    assert {"anthropic", "google", "tencent", "nvidia", "cohere", "cursor", "meta"} <= set(
        grouped
    )
    for organization in ("anthropic", "tencent", "google"):
        channels = [source.channel for source in grouped[organization]]
        assert len(channels) >= 2, organization


def test_anthropic_channels_share_one_organization() -> None:
    grouped = organization_map()["anthropic"]
    assert {source.channel for source in grouped} == {"news", "research", "engineering"}
    assert all(source.organization == "anthropic" for source in grouped)


def test_every_new_channel_declares_its_company() -> None:
    for source_id, (organization, channel) in NEW_CHANNELS.items():
        source = source_by_id(source_id)
        assert source.organization == organization, source_id
        assert source.channel == channel, source_id
        assert source.source_type == "official", source_id
        assert source.url.startswith("https://"), source_id


def test_new_official_channels_stay_inside_the_official_priority_band() -> None:
    """Official must keep outranking research, which keeps outranking media."""
    priorities = {source.id: source.priority for source in enabled_sources()}
    official = [p for s, p in priorities.items() if source_by_id(s).source_type == "official"]
    research = [p for s, p in priorities.items() if source_by_id(s).source_type == "research"]
    media = [p for s, p in priorities.items() if source_by_id(s).source_type == "media"]

    assert max(official) < min(research)
    assert max(research) < min(media)
    for source_id in NEW_CHANNELS:
        assert priorities[source_id] in official


def test_source_names_are_unique_because_dedupe_keys_on_them() -> None:
    """Event dedup looks priorities up by ``source.name``.

    Two sources sharing a name would silently overwrite each other's priority,
    so a company's channels must be named distinctly.
    """
    names = [source.name for source in all_sources()]
    assert len(set(names)) == len(names)


# --- C. Anthropic multi-path ---


def test_anthropic_newsroom_collects_news_articles() -> None:
    entries = anthropic_entries(ANTHROPIC_NEWS)
    urls = {url for url, _t, _p in entries}

    assert "https://www.anthropic.com/news/claude-opus-5" in urls
    assert "https://www.anthropic.com/news/wellbeing-research-grants" in urls


def test_anthropic_institute_essay_is_no_longer_dropped() -> None:
    """The regression this phase exists for.

    The essay is linked with an absolute URL and lives under ``/institute/``, so
    a ``href^="/news/"`` selector — the old rule — never saw it.
    """
    page = (
        '<html><body><a class="FeaturedGrid-module-scss-module__W1FydW__sideLink" '
        'href="https://www.anthropic.com/institute/measuring-pace-of-ai-development">'
        "<div><time>Sep 17, 2026</time></div>"
        "<h4>Measurements for understanding the pace of AI development</h4></a>"
        "</body></html>"
    )
    entries = anthropic_entries(page)

    assert entries == [
        (
            "https://www.anthropic.com/institute/measuring-pace-of-ai-development",
            "Measurements for understanding the pace of AI development",
            datetime(2026, 9, 17, tzinfo=UTC),
        )
    ]


def test_anthropic_root_level_posts_are_collected_too() -> None:
    """A model announcement sits at the top level, not under ``/news/``."""
    page = (
        '<html><body><a class="FeaturedGrid-module-scss-module__W1FydW__content" '
        'href="/claude-fable-and-mythos-5-1">'
        '<h2 class="headline-4">Introducing Claude Fable 5.1 and Claude Mythos 5.1</h2>'
        "<div><span>Announcements</span><time>Sep 1, 2026</time></div></a>"
        "</body></html>"
    )
    entries = anthropic_entries(page)

    assert [url for url, _t, _p in entries] == [
        "https://www.anthropic.com/claude-fable-and-mythos-5-1"
    ]


@pytest.mark.parametrize(
    "href",
    [
        "/category/product",
        "/tag/announcements",
        "/author/dario-amodei",
        "/research/team/alignment",
    ],
)
def test_anthropic_non_article_paths_stay_out(href: str) -> None:
    """Category, tag, author and team pages are not articles.

    The rule that admits top-level posts is "the card carries its own date", and
    an index link never does, so these stay excluded without a path blacklist.
    """
    page = (
        f'<html><body><a href="{href}"><h3>An index page</h3></a>'
        '<a href="/news/real-post"><time>Sep 1, 2026</time><h3>Real</h3></a></body></html>'
    )
    urls = {url for url, _t, _p in anthropic_entries(page)}

    assert urls == {"https://www.anthropic.com/news/real-post"}


def test_anthropic_research_index_parses_without_team_pages() -> None:
    entries = anthropic_research_entries(ANTHROPIC_RESEARCH)
    urls = {url for url, _t, _p in entries}

    assert "https://www.anthropic.com/research/alignment-assessment-cybersecurity-incidents" in urls
    assert all("/research/team/" not in url for url in urls)


def test_anthropic_research_skips_an_undated_card() -> None:
    entries = anthropic_research_entries(ANTHROPIC_RESEARCH)

    assert all("undated-note" not in url for url, _t, _p in entries)


def test_anthropic_engineering_reads_the_date_from_its_own_element() -> None:
    """This blog prints the date in a div and its featured card has none."""
    entries = anthropic_engineering_entries(ANTHROPIC_ENGINEERING)
    by_url = {url: (title, published) for url, title, published in entries}

    assert by_url["https://www.anthropic.com/engineering/april-23-postmortem"] == (
        "An update on recent Claude Code quality reports",
        datetime(2026, 4, 23, tzinfo=UTC),
    )
    assert all("how-we-contain-claude" not in url for url in by_url)


def test_anthropic_engine_blog_without_cards_is_a_structure_change() -> None:
    with pytest.raises(PageStructureError):
        anthropic_engineering_entries("<html><body><p>Redesigned</p></body></html>")


# --- D. Tencent multi-channel ---


def test_tencent_hunyuan_and_cloud_are_separate_channels() -> None:
    """Coverage of one Tencent channel says nothing about the others."""
    hunyuan = source_by_id("tencent-hunyuan")
    cloud = source_by_id("tencent-cloud-ai")
    workbuddy = source_by_id("tencent-workbuddy")

    assert {hunyuan.channel, cloud.channel, workbuddy.channel} == {"model", "cloud", "product"}
    assert hunyuan.organization == cloud.organization == workbuddy.organization == "tencent"
    assert len({hunyuan.url, cloud.url, workbuddy.url}) == 3


def test_tencent_cloud_announcements_parse_title_and_timestamp() -> None:
    entries = tencent_cloud_entries(TENCENT_CLOUD)
    by_url = {url: (title, published) for url, title, published in entries}

    url = "https://cloud.tencent.com/announce/detail/2479"
    assert url in by_url
    title, published = by_url[url]
    assert "GLM-5v-Turbo" in title
    assert published == datetime(2026, 9, 17, 15, 13, 49, tzinfo=UTC)


def test_tencent_cloud_listing_without_rows_is_a_structure_change() -> None:
    with pytest.raises(PageStructureError):
        tencent_cloud_entries("<html><body><p>Announcements moved.</p></body></html>")


def test_workbuddy_releases_parse_version_and_date() -> None:
    entries = tencent_workbuddy_entries(TENCENT_WORKBUDDY)

    url, title, published = entries[0]
    assert "5.5.6" in title
    assert published == datetime(2026, 9, 10, tzinfo=UTC)
    assert "release=5.5.6" in url


def test_workbuddy_releases_do_not_collapse_into_one_entry() -> None:
    """Seventy releases on one page must stay separate entries."""
    entries = tencent_workbuddy_entries(TENCENT_WORKBUDDY)
    urls = [url for url, _t, _p in entries]

    assert len(urls) == len(set(urls)) == 3


def test_workbuddy_changelog_without_headings_is_a_structure_change() -> None:
    with pytest.raises(PageStructureError):
        tencent_workbuddy_entries("<html><body><p>Docs moved.</p></body></html>")


# --- E. wide official feeds are AI filtered ---


def test_a_wide_official_channel_drops_non_ai_rows() -> None:
    """腾讯云's announcement list carries billing, databases and load balancers.

    Only the AI part belongs in an AI digest, and the AI filter has to make that
    call before the row reaches the window or the LLM.
    """
    result = parse_html_page(source_by_id("tencent-cloud-ai"), index_html=TENCENT_CLOUD)

    kept = [article.title for article in result.valid]
    assert kept, "the AI relevant row must survive"
    assert any("GLM" in title for title in kept)
    assert all("互动直播" not in title for title in kept)
    assert all("负载均衡" not in title for title in kept)
    assert result.skipped >= 1
    assert result.success is True


def test_a_wide_official_channel_is_marked_for_filtering() -> None:
    for source_id in ("tencent-cloud-ai", "nvidia", "google-cloud-ai"):
        assert source_by_id(source_id).requires_ai_filter is True, source_id


def test_a_narrow_official_channel_is_not_filtered() -> None:
    """A channel with nothing to exclude must not pay the recall cost.

    NVIDIA's developer blog carries no game promotions, and the AI filter would
    drop real posts whose titles use none of its keywords ("Dense vs. MoE
    Models", "BioNeMo Inference Runtime"), so it is collected unfiltered.
    """
    for source_id in ("anthropic", "tencent-workbuddy", "meta-ai-blog", "nvidia-developer"):
        assert source_by_id(source_id).requires_ai_filter is False, source_id


def test_an_already_scoped_channel_is_not_ai_filtered() -> None:
    """Anthropic's newsroom is all AI news; filtering it would only cost work."""
    for source_id in ("anthropic", "tencent-workbuddy", "meta-ai-blog"):
        assert source_by_id(source_id).requires_ai_filter is False, source_id


# --- H. source failure isolation ---


def test_one_broken_channel_does_not_affect_a_companys_others() -> None:
    def fetch(url: str, timeout: float = 10.0) -> str:
        if "anthropic.com/engineering" in url:
            return "<html><body><p>Redesigned entirely.</p></body></html>"
        if "anthropic.com/research" in url:
            return ANTHROPIC_RESEARCH
        return ANTHROPIC_NEWS

    news = collect_html_source(source_by_id("anthropic"), fetch_text=fetch)
    research = collect_html_source(source_by_id("anthropic-research"), fetch_text=fetch)
    engineering = collect_html_source(source_by_id("anthropic-engineering"), fetch_text=fetch)

    assert news.success is True and news.valid
    assert research.success is True and research.valid
    assert engineering.success is False
    assert engineering.error


# --- Meta AI blog (hashed classes, read structurally) ---


# --- catalogue-shaped sources carry their own summary ---


def test_alibaba_catalogue_rows_become_dated_entries() -> None:
    """A model catalogue is a table, not a list of pages.

    Rows have no anchor of their own, so the model id is the row's identity and
    travels in the URL as a query value. Without that every row would share one
    canonical URL and the whole catalogue would collapse to a single entry.
    """
    entries = alibaba_model_entries(ALIBABA_MODELS)
    urls = [entry[0] for entry in entries]

    assert len(urls) == len(set(urls)) == 4
    assert all("?model=" in url for url in urls)
    assert entries[0][1].startswith("HappyOyster")
    assert entries[0][2] == datetime(2026, 9, 17, tzinfo=UTC)


def test_alibaba_catalogue_carries_its_description_as_the_summary() -> None:
    """The catalogue's own text is the only body the digest can use.

    Its page is a repeated table that body extraction rejects as low quality, so
    without the description column the digest would see a bare model id.
    """
    result = parse_html_page(
        source_by_id("alibaba-model-studio"), index_html=ALIBABA_MODELS
    )

    assert result.success is True
    assert all(article.summary for article in result.valid)
    assert any("世界模型" in article.summary for article in result.valid)


def test_alibaba_catalogue_without_tables_is_a_structure_change() -> None:
    with pytest.raises(PageStructureError):
        alibaba_model_entries("<html><body><p>Catalogue moved.</p></body></html>")


def test_cohere_research_dates_come_from_the_paper_slug() -> None:
    """The cards print no ``<time>``; the date ends each permalink."""
    entries = cohere_research_entries(COHERE_RESEARCH)

    assert entries[0] == (
        "https://cohere.com/research/papers/building-multilingual-bridges-2026-09-10",
        "Building Multilingual Bridges",
        datetime(2026, 9, 10, tzinfo=UTC),
    )


def test_cursor_changelog_titles_are_headlines_not_dates() -> None:
    """The same href appears on the date link and on the heading link."""
    entries = cursor_changelog_entries(CURSOR_CHANGELOG)
    titles = [title for _u, title, _p in entries]

    assert "Cursor Projects" in titles
    assert all("2026" not in title for title in titles)


# --- Meta AI blog (hashed classes, read structurally) ---


def test_meta_blog_cards_parse_headline_and_date() -> None:
    entries = meta_ai_entries(META_AI)

    assert entries[0] == (
        "https://ai.meta.com/blog/introducing-muse-spark-meta-model-api/",
        "Introducing Muse Spark 1.1",
        datetime(2026, 7, 9, tzinfo=UTC),
    )


def test_meta_blog_featured_tag_is_not_a_title() -> None:
    """The featured card tags itself "FEATURED" on its own anchor."""
    entries = meta_ai_entries(META_AI)

    assert all(title.strip().lower() != "featured" for _u, title, _p in entries)


def test_meta_blog_page_without_links_is_a_structure_change() -> None:
    with pytest.raises(PageStructureError):
        meta_ai_entries("<html><body><p>Nothing.</p></body></html>")


# --- empty listings are not structure changes ---


@pytest.mark.parametrize("source_id", sorted(NEW_CHANNELS))
def test_an_empty_html_channel_succeeds_with_nothing(source_id: str) -> None:
    """A quiet channel and a moved page must not look the same."""
    source = source_by_id(source_id)
    if source.kind != "html":
        pytest.skip("RSS sources answer with an empty feed instead")
    result = parse_html_page(source, index_html=EMPTY_HTML[source_id])

    assert result.success is True, result.error
    assert result.valid == []


# --- source health: OK / EMPTY / FAIL / UNSUPPORTED ---


class _Outcome:
    """A CollectResult stand-in for the health report."""

    def __init__(
        self,
        source_id: str,
        name: str,
        *,
        success: bool = True,
        valid: int = 0,
        error=None,
    ):
        self.source_id = source_id
        self.source_name = name
        self.success = success
        self.fetched = valid
        self.valid = [object() for _ in range(valid)]
        self.error = error


def test_health_separates_quiet_from_broken() -> None:
    report = build_report(
        [
            _Outcome("openai", "OpenAI", valid=3),
            _Outcome("anthropic-research", "Anthropic Research", valid=0),
            _Outcome(
                "anthropic-engineering",
                "Anthropic Engineering",
                success=False,
                error="HTTP 500",
            ),
        ]
    )
    by_id = {outcome.source_id: outcome for outcome in report.outcomes}

    assert by_id["openai"].status == OK
    assert by_id["anthropic-research"].status == EMPTY
    assert by_id["anthropic-engineering"].status == FAIL


def test_health_reports_the_company_and_channel_of_each_source() -> None:
    report = build_report([_Outcome("anthropic-research", "Anthropic Research", valid=2)])
    outcome = report.outcomes[0]

    assert outcome.organization == "anthropic"
    assert outcome.channel == "research"


def test_coverage_groups_by_company_and_marks_unsupported_channels() -> None:
    report = build_report(
        [
            _Outcome("anthropic", "Anthropic", valid=2),
            _Outcome("anthropic-research", "Anthropic Research", valid=1),
            _Outcome("anthropic-engineering", "Anthropic Engineering", valid=0),
        ]
    )
    rows = build_coverage(report, unsupported=unsupported_channels())
    rendered = format_official_coverage(rows)
    lines = rendered.splitlines()

    assert lines[0] == "Official Source Coverage"
    assert "anthropic" in lines
    assert any(line.strip().startswith("news") and OK in line for line in lines)
    assert any(line.strip().startswith("engineering") and EMPTY in line for line in lines)
    assert any(UNSUPPORTED in line for line in lines)


def test_coverage_prints_every_audited_company() -> None:
    """Every company in the audit appears, including the unsupported gaps.

    A real refresh reports once per enabled source, so this mirrors that: one
    outcome per configured source, then the unsupported channels folded in.
    """
    outcomes = [
        _Outcome(source.id, source.name, valid=1) for source in enabled_sources()
    ]
    rendered = format_official_coverage(
        build_coverage(build_report(outcomes), unsupported=unsupported_channels())
    )

    for organization in (
        "openai",
        "anthropic",
        "google",
        "meta",
        "nvidia",
        "deepseek",
        "alibaba",
        "moonshot",
        "mistral",
        "cohere",
        "cursor",
        "bytedance",
        "tencent",
        "baidu",
        "zhipu",
        "minimax",
    ):
        assert organization in rendered, organization


def test_unsupported_channels_are_recorded_with_a_reason() -> None:
    from app.config.sources import UNSUPPORTED_CHANNELS

    for organization, channel, reason in UNSUPPORTED_CHANNELS:
        assert organization and channel in NEWS_CHANNELS
        assert reason.strip(), f"{organization}/{channel} needs a reason"


def test_an_empty_report_still_renders_the_coverage_header() -> None:
    assert format_official_coverage([]) == "Official Source Coverage"


# --- F/G. one event, one entry, and the official surface wins ---


def _news(
    news_id: str,
    *,
    source: str,
    source_type: str,
    title: str,
    summary: str,
    published: str,
    importance: int | None = None,
):
    from app.models import NewsCategory, NewsItem

    return NewsItem(
        id=news_id,
        title_cn=title,
        title_original=title,
        summary=summary,
        why_it_matters="",
        source=source,
        source_type=source_type,
        published_at=published,
        category=NewsCategory.highlight,
        tags=[source],
        url=f"https://example.com/{news_id}",
        importance_score=importance,
    )


def test_one_event_from_three_surfaces_becomes_one_entry() -> None:
    """Two official channels of one company plus media is still one story.

    A company publishing on several official surfaces is exactly what makes
    this likely: the newsroom, the developer blog and a reporter can all cover
    one launch, and the digest must show it once.
    """
    from app.services.event_dedup import dedupe_events

    announcement = "Anthropic ships Claude Fable 5.1 with a longer context window"
    body = (
        "Anthropic announced Claude Fable 5.1 today, a frontier model for "
        "long-horizon agentic coding work with a longer context window, "
        "available today in the API."
    )
    items = [
        _news(
            "official-news",
            source="Anthropic",
            source_type="official",
            title=announcement,
            summary=body,
            published="2026-09-12T06:00:00+00:00",
            importance=88,
        ),
        _news(
            "official-engineering",
            source="Anthropic Engineering",
            source_type="official",
            title=announcement,
            summary=(
                body + " The engineering notes describe the coding harness changes."
            ),
            published="2026-09-12T07:00:00+00:00",
            importance=80,
        ),
        _news(
            "media",
            source="TechCrunch AI",
            source_type="media",
            title=announcement + " for agentic coding",
            summary=body,
            published="2026-09-12T09:00:00+00:00",
            importance=85,
        ),
    ]
    kept, stats = dedupe_events(items)

    assert len(kept) == 1
    assert stats.merged == 2
    assert kept[0].source_type == "official"


def test_an_official_surface_beats_media_for_the_same_event() -> None:
    """The representative entry is the vendor's, not the reporter's.

    Media is allowed to carry a higher ``importance_score`` and still lose:
    class comes first, which is what keeps a second-hand write-up from standing
    in for the announcement it describes.
    """
    from app.services.event_dedup import dedupe_events

    title = "Tencent Cloud ships WorkBuddy 5.5.6 for automated office tasks"
    body = (
        "Tencent Cloud released WorkBuddy 5.5.6 today, adding automated office "
        "tasks and a faster agent runtime, available to all cloud customers."
    )
    items = [
        _news(
            "media",
            source="TechCrunch AI",
            source_type="media",
            title=title,
            summary=body,
            published="2026-09-10T09:00:00+00:00",
            importance=95,
        ),
        _news(
            "official",
            source="腾讯 WorkBuddy",
            source_type="official",
            title=title,
            summary=body,
            published="2026-09-10T06:00:00+00:00",
            importance=62,
        ),
    ]
    kept, _stats = dedupe_events(items)

    assert len(kept) == 1
    assert kept[0].source == "腾讯 WorkBuddy"
    assert kept[0].source_type == "official"


def test_rss_and_html_channels_apply_the_same_ai_filter() -> None:
    """A wide feed is filtered whichever collector reads it.

    ``requires_ai_filter`` used to be honoured only on the RSS path, so an HTML
    source carrying the same flag would have let every non-AI row through.
    """
    from app.collectors.rss import parse_feed

    cloud = source_by_id("tencent-cloud-ai")
    assert cloud.requires_ai_filter is True

    html_result = parse_html_page(cloud, index_html=TENCENT_CLOUD)
    assert html_result.skipped >= 1

    feed = _rss_with(
        [
            ("腾讯云数据库产品降价", "https://cloud.tencent.com/announce/detail/1"),
            ("腾讯云 GLM-5v-Turbo 模型下线通知", "https://cloud.tencent.com/announce/detail/2"),
        ]
    )
    rss_source = source_by_id("openai")
    from dataclasses import replace

    rss_result = parse_feed(feed, replace(rss_source, requires_ai_filter=True))
    assert len(rss_result.valid) == 1


def _rss_with(items: list[tuple[str, str]]) -> str:
    from email.utils import format_datetime

    stamp = format_datetime(datetime(2026, 9, 10, 6, 0, tzinfo=UTC))
    entries = "\n".join(
        f"<item><title>{title}</title><link>{url}</link>"
        f'<guid isPermaLink="true">{url}</guid><pubDate>{stamp}</pubDate></item>'
        for title, url in items
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0"><channel><title>Feed</title>'
        f"{entries}</channel></rss>"
    )
