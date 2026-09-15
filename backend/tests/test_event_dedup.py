"""Phase 10.4: one event, one digest entry.

The rule layer already removes the same URL and byte-equal titles, but it cannot
see that OpenAI announcing a model, TechCrunch reporting it and a second outlet
re-reporting it are one event told three ways. These tests cover the second,
conservative layer that folds those reports together, in both directions: the
duplicates that must merge and, more importantly, the near-misses that must not.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest

from app.config.sources import enabled_sources
from app.db.repositories import NewsRepository
from app.db.session import new_session
from app.models import NewsCategory, NewsItem
from app.services.digest_store import DigestStore, store
from app.services.digest_window import DigestWindow
from app.services.event_dedup import (
    DEFAULT_SETTINGS,
    choose_main_news,
    dedupe_events,
    format_event_dedup,
    log_event_dedup,
    match_event,
)
from tests.conftest import EMPTY_HTML, EMPTY_RSS

UTC = timezone.utc

# The window every digest-level test writes against, and the date a refresh at
# WINDOW_END produces (2026-09-13 16:00 UTC is 2026-09-14 in Asia/Shanghai).
WINDOW_START = datetime(2026, 9, 12, 16, 0, tzinfo=UTC)
WINDOW_END = datetime(2026, 9, 13, 16, 0, tzinfo=UTC)
DIGEST_DATE = "2026-09-14"


def at(hour: int, minute: int = 0) -> str:
    """An ISO timestamp inside the test window."""
    return datetime(2026, 9, 13, hour, minute, tzinfo=UTC).isoformat()


def item(
    news_id: str,
    *,
    source: str = "OpenAI",
    source_type: str = "official",
    title: str = "Title",
    title_cn: str = "",
    summary: str = "",
    why: str = "",
    published: str | None = None,
    importance: int | None = None,
) -> NewsItem:
    return NewsItem(
        id=news_id,
        title_cn=title_cn or title,
        title_original=title,
        summary=summary,
        why_it_matters=why,
        source=source,
        source_type=source_type,
        published_at=at(6) if published is None else published,
        category=NewsCategory.highlight,
        tags=[source],
        url=f"https://example.com/{news_id}",
        importance_score=importance,
    )


# One release, told by the official source and by two second-hand reports.
ANNOUNCEMENT = "Introducing GPT-6 Astra"
ANNOUNCEMENT_CN = "OpenAI 发布 GPT-6 Astra 新模型"
SUMMARY = (
    "A new frontier model for long-horizon agentic work and enterprise tasks, "
    "available today in the API."
)
# Deliberately not a translation of SUMMARY: two outlets paraphrase the same
# fact in their own words, which is what the merge rule has to see through.
SUMMARY_CN = "面向企业长任务的前沿模型，支持长程 agentic 工作。"


def official_announcement() -> NewsItem:
    return item(
        "official",
        source="OpenAI",
        source_type="official",
        title=ANNOUNCEMENT,
        title_cn=ANNOUNCEMENT_CN,
        summary=SUMMARY,
        why=SUMMARY_CN,
    )


def techcrunch_report() -> NewsItem:
    return item(
        "media",
        source="TechCrunch AI",
        source_type="media",
        title="OpenAI launches GPT-6 Astra, a new frontier model",
        title_cn="OpenAI 推出 GPT-6 Astra 前沿模型",
        summary=(
            "A new frontier model for long-horizon agentic work and enterprise "
            "tasks is available today."
        ),
        why=SUMMARY_CN,
        published=at(8),
        importance=90,
    )


def ars_report() -> NewsItem:
    """A second-hand report of the same launch, in the source set's media class.

    It used to be a 量子位 write-up, and 量子位 was removed as a source in Phase
    10.11. The property this fixture exists for is unchanged: a media source
    reporting the same event as the vendor, with a different language and
    wording, must merge into one digest entry.
    """
    return item(
        "ars",
        source="Ars Technica",
        source_type="media",
        title="OpenAI 发布 GPT-6 Astra，面向企业长任务",
        title_cn="OpenAI 发布 GPT-6 Astra 新模型",
        summary="新模型面向企业长任务与 agentic 工作。",
        why="面向企业长任务的前沿模型。",
        published=at(9),
        importance=80,
    )


def window() -> DigestWindow:
    return DigestWindow(start=WINDOW_START, end=WINDOW_END)


# --- the similarity rule ---


def test_near_identical_event_across_sources_merges() -> None:
    match = match_event(official_announcement(), techcrunch_report())

    assert match is not None
    assert match.reason == "shared_term_text_similarity"
    assert match.shared_terms == ("gpt-6",)
    assert match.score >= 0.6
    assert match.hours_apart == 2.0
    # The reason is explicit, so a wrong merge points at one signal.
    assert "reason=shared_term_text_similarity" in match.describe()


def test_official_and_chinese_media_merge_on_the_shared_model_name() -> None:
    match = match_event(official_announcement(), ars_report())

    assert match is not None
    assert match.shared_terms == ("gpt-6",)


def test_same_url_is_already_handled_by_the_rule_layer() -> None:
    """Near-identical event or not, one URL is one news_id, so nothing merges."""
    first = item("a", title=ANNOUNCEMENT, summary=SUMMARY)
    second = first.model_copy(update={"source": "Ars Technica", "source_type": "media"})

    assert match_event(first, second) is not None
    # A digest can never see both: they share an id, so the link list already
    # holds a single row before event dedup even runs.
    kept, stats = dedupe_events([first, second])
    assert [entry.id for entry in kept] == ["a"]
    assert stats.merged == 1


def test_same_model_different_event_does_not_merge() -> None:
    """A follow-up story shares the model name but is not the announcement."""
    pricing = item(
        "pricing",
        source="TechCrunch AI",
        source_type="media",
        title="GPT-6 Astra API pricing drops 50%",
        title_cn="GPT-6 Astra API 价格下调 50%",
        summary="OpenAI cut API pricing for the Astra model by half this quarter.",
        why="OpenAI 将 Astra 的 API 价格下调一半。",
        published=at(8),
    )

    assert match_event(official_announcement(), pricing) is None


def test_contradictory_outcome_does_not_merge() -> None:
    """Two reports of opposite results are two stories about one subject."""
    fails = item(
        "fails",
        source="TechCrunch AI",
        source_type="media",
        title="GPT-6 Astra fails safety benchmark",
        title_cn="GPT-6 Astra 未通过安全测试",
        summary="Researchers found the model fails several safety evaluations.",
    )
    passes = item(
        "passes",
        source="Ars Technica",
        source_type="media",
        title="GPT-6 Astra passes safety benchmark",
        title_cn="GPT-6 Astra 通过安全测试",
        summary="The model passed all safety evaluations.",
        published=at(8),
    )

    assert match_event(fails, passes) is None


def test_two_different_versions_do_not_merge() -> None:
    """Identical wording, different version: still two announcements."""
    five = item("gpt5", title="Introducing GPT-5", summary=SUMMARY)
    six = item(
        "gpt6",
        source="Google DeepMind",
        title="Introducing GPT-6",
        summary=SUMMARY,
        published=at(8),
    )

    assert match_event(five, six) is None


def test_funding_story_translated_across_languages_merges() -> None:
    """Two paraphrases of one round: the headline and the figure agree."""
    english = item(
        "en",
        source="TechCrunch AI",
        source_type="media",
        title="Mecka AI nears 500M valuation in Sequoia-led deal",
        title_cn="Mecka AI 获红杉领投，估值接近 5 亿美元",
        summary="Sequoia led the round for the robotics startup.",
        why="红杉领投该机器人创业公司。",
    )
    chinese = item(
        "cn",
        source="Ars Technica",
        source_type="media",
        title="Mecka AI nears 500M valuation",
        title_cn="Mecka AI 估值接近 5 亿美元",
        summary="The robotics startup is raising at a 500M valuation led by Sequoia.",
        why="机器人创业公司以 5 亿美元估值融资。",
        published=at(8),
    )

    match = match_event(english, chinese)
    assert match is not None
    assert match.reason == "same_headline_and_figure"
    assert match.shared_terms == ("500m",)


def test_different_funding_amounts_do_not_merge() -> None:
    """Same company, same day, different round size: two separate facts."""
    five = item(
        "500m",
        source="TechCrunch AI",
        source_type="media",
        title="Mecka AI nears 500M valuation",
        title_cn="Mecka AI 估值接近 5 亿美元",
        summary="Sequoia led the round for the robotics startup.",
    )
    eight = item(
        "800m",
        source="Ars Technica",
        source_type="media",
        title="Mecka AI nears 800M valuation",
        title_cn="Mecka AI 估值接近 8 亿美元",
        summary="A different round with a higher valuation.",
        published=at(8),
    )

    assert match_event(five, eight) is None


def test_unrelated_news_stays_apart() -> None:
    nvidia = item(
        "nvidia",
        source="NVIDIA",
        title="NVIDIA opens robotics lab in Tokyo",
        title_cn="NVIDIA 在东京开设机器人实验室",
        summary="The lab will research physical AI.",
        published=at(8),
    )

    assert match_event(official_announcement(), nvidia) is None


def test_same_source_two_different_topics_do_not_merge() -> None:
    """Sharing a company is not sharing an event."""
    funding = item(
        "funding",
        title="OpenAI raises safety funding",
        title_cn="OpenAI 增加安全投入",
        summary="The company will fund external safety research.",
    )
    office = item(
        "office",
        source="TechCrunch AI",
        source_type="media",
        title="OpenAI opens Tokyo office",
        title_cn="OpenAI 在东京开设办公室",
        summary="The office will support enterprise customers.",
        published=at(8),
    )

    assert match_event(funding, office) is None


def test_undated_article_is_never_an_event_candidate() -> None:
    undated = official_announcement().model_copy(update={"published_at": ""})

    assert match_event(undated, techcrunch_report()) is None


def test_news_outside_the_horizon_does_not_merge() -> None:
    """The same story told three days later is a different, later mention."""
    three_days_later = item(
        "later",
        source="TechCrunch AI",
        source_type="media",
        title="OpenAI GPT-6 Astra rollout continues",
        summary="The rollout continues this week.",
        published="2026-09-16T06:00:00+00:00",
    )

    assert match_event(official_announcement(), three_days_later) is None


def test_bare_headlines_merge_only_on_an_almost_exact_match() -> None:
    first = item("a", title="OpenAI launches GPT-6 Astra")
    same = item(
        "b",
        source="TechCrunch AI",
        source_type="media",
        title="OpenAI launches GPT-6 Astra",
    )
    different = item(
        "c", source="Ars Technica", source_type="media", title="OpenAI ships a new chat app"
    )

    assert match_event(first, same) is not None
    assert match_event(first, different) is None


# --- clusters ---


def test_three_reports_of_one_event_become_one_entry() -> None:
    kept, stats = dedupe_events([official_announcement(), techcrunch_report(), ars_report()])

    assert [entry.id for entry in kept] == ["official"]
    assert stats.candidates == 3
    assert stats.clusters == 1
    assert stats.merged == 2
    assert stats.decisions[0].kept.id == "official"
    assert {merged.id for merged, _ in stats.decisions[0].merged} == {"media", "ars"}


def test_unrelated_news_keeps_every_entry() -> None:
    nvidia = item("nvidia", source="NVIDIA", title="NVIDIA opens robotics lab in Tokyo")
    kept, stats = dedupe_events([official_announcement(), nvidia])

    assert [entry.id for entry in kept] == ["official", "nvidia"]
    assert stats.merged == 0
    assert stats.decisions == []
    assert stats.reduced is False


def test_input_order_is_preserved_in_the_output() -> None:
    """The digest shows entries in the order its caller established."""
    nvidia = item("nvidia", source="NVIDIA", title="NVIDIA opens robotics lab in Tokyo")

    kept, _ = dedupe_events([nvidia, techcrunch_report(), official_announcement()])

    assert [entry.id for entry in kept] == ["nvidia", "official"]


def test_a_later_mention_cannot_revive_a_merged_duplicate() -> None:
    """Re-running with the duplicate back in the input still folds it away."""
    first, _ = dedupe_events([official_announcement(), techcrunch_report()])
    assert [entry.id for entry in first] == ["official"]

    kept, stats = dedupe_events([*first, techcrunch_report()])

    assert [entry.id for entry in kept] == ["official"]
    assert stats.merged == 1


def test_cluster_collapses_a_chain_whose_ends_do_not_match() -> None:
    """Comparing against every member, not just the first, closes the chain."""
    russian = techcrunch_report().model_copy(
        update={
            "id": "middle",
            "source": "TechCrunch AI",
            "source_type": "media",
            "title_cn": "OpenAI 推出 GPT-6 Astra 前沿模型",
            "summary": SUMMARY_CN,
            "why_it_matters": "",
        }
    )

    kept, stats = dedupe_events([official_announcement(), russian, ars_report()])

    assert len(kept) == 1
    assert stats.clusters == 1
    assert stats.merged == 2


# --- main-news selection ---


def test_official_source_becomes_the_main_news() -> None:
    cluster = [ars_report(), techcrunch_report(), official_announcement()]

    assert choose_main_news(cluster).id == "official"
    # Collection order must not decide it.
    assert choose_main_news(list(reversed(cluster))).id == "official"


def test_research_source_outranks_media() -> None:
    """Hugging Face is ``research`` since Phase 10.11, and still beats the press."""
    huggingface = item(
        "hf",
        source="Hugging Face",
        source_type="research",
        title="A guide to evaluating agents",
    )
    second_hand = item(
        "ars",
        source="Ars Technica",
        source_type="media",
        title="智能体评测指南",
        importance=99,
    )

    assert choose_main_news([second_hand, huggingface]).id == "hf"


def test_every_configured_source_type_has_a_rank() -> None:
    """The main-news rule reads the same class names the config declares.

    A source type with no entry here is treated as unknown, which sorts *after*
    media — the opposite of the intended order. Phase 10.11's ``blog`` ->
    ``research`` rename hit exactly that, so the table is checked against the
    config rather than against a hand-written list.
    """
    from app.config.sources import NEWS_SOURCE_TYPES
    from app.services.event_dedup import SOURCE_TYPE_RANK

    missing = [name for name in NEWS_SOURCE_TYPES if name not in SOURCE_TYPE_RANK]
    assert missing == []
    assert SOURCE_TYPE_RANK["official"] < SOURCE_TYPE_RANK["research"]
    assert SOURCE_TYPE_RANK["research"] < SOURCE_TYPE_RANK["media"]


def test_configured_priority_orders_sources_of_one_class() -> None:
    techcrunch = item("tc", source="TechCrunch AI", source_type="media", title="Same story")
    second_hand = item("qb", source="Ars Technica", source_type="media", title="同一事件")

    assert choose_main_news([second_hand, techcrunch]).id == "tc"


def test_importance_and_completeness_break_ties_within_a_source_class() -> None:
    thin = item("thin", title="Announcement", summary="short", importance=10)
    rich = item(
        "rich",
        title="Announcement",
        summary="a much more complete summary of the same announcement",
        importance=90,
    )

    assert choose_main_news([thin, rich]).id == "rich"


def test_the_earliest_report_wins_a_complete_tie() -> None:
    early = item("early", title="Announcement", published=at(3))
    late = item("late", title="Announcement", published=at(9))

    assert choose_main_news([late, early]).id == "early"


# --- observability ---


def test_summary_is_logged_at_info_and_detail_only_behind_debug(caplog) -> None:
    _, stats = dedupe_events([official_announcement(), techcrunch_report()])

    with caplog.at_level("INFO", logger="app.services.event_dedup"):
        log_event_dedup(stats)
    assert "candidates=2 clusters=1 merged=1" in caplog.text
    # The default line must not carry per-item detail.
    assert "MERGE" not in caplog.text

    caplog.clear()
    with caplog.at_level("INFO", logger="app.services.event_dedup"):
        log_event_dedup(stats, debug=True)
    assert "MERGE" in caplog.text
    assert "reason=" in caplog.text


def test_debug_view_names_the_kept_and_merged_items() -> None:
    _, stats = dedupe_events([official_announcement(), techcrunch_report()])

    rendered = format_event_dedup(stats.decisions[0])
    assert rendered.startswith("KEEP OpenAI:")
    assert "MERGE TechCrunch AI:" in rendered
    assert "reason=shared_term_text_similarity" in rendered
    assert "score=" in rendered


def test_every_folded_item_carries_a_real_reason() -> None:
    """A merge must always be explainable, whichever item seeded the cluster.

    Here the media report sorts first, so the official announcement joins the
    cluster afterwards and becomes the winner. The seed is then folded without
    ever having been compared to the winner, and its reason has to be recovered
    rather than left as a placeholder.
    """
    _, stats = dedupe_events([official_announcement(), techcrunch_report()])

    reasons = {match.reason for _, match in stats.decisions[0].merged}
    assert reasons == {"shared_term_text_similarity"}
    assert all(match.score > 0 for _, match in stats.decisions[0].merged)


def test_empty_input_logs_nothing(caplog) -> None:
    kept, stats = dedupe_events([])

    with caplog.at_level("INFO", logger="app.services.event_dedup"):
        log_event_dedup(stats)
    assert caplog.text == ""
    assert kept == []


def test_persist_logs_the_summary_and_keeps_detail_behind_an_env_flag(
    caplog, monkeypatch
) -> None:
    """The refresh log gains one summary line; per-cluster detail is opt-in."""
    monkeypatch.delenv("AI_DAILY_DEBUG_EVENT_DEDUP", raising=False)
    events = DigestStore()

    with caplog.at_level("INFO", logger="app.services.event_dedup"):
        events.persist(
            date=DIGEST_DATE,
            window=window(),
            news_items=[official_announcement(), techcrunch_report(), ars_report()],
            github_projects=[],
        )
    assert "candidates=3 clusters=1 merged=2" in caplog.text
    assert "MERGE" not in caplog.text

    caplog.clear()
    monkeypatch.setenv("AI_DAILY_DEBUG_EVENT_DEDUP", "1")
    with caplog.at_level("INFO", logger="app.services.event_dedup"):
        events.persist(
            date=DIGEST_DATE,
            window=window(),
            news_items=[official_announcement(), techcrunch_report(), ars_report()],
            github_projects=[],
        )
    assert "KEEP OpenAI:" in caplog.text
    assert "MERGE TechCrunch AI:" in caplog.text


# --- digest persistence ---


def test_persist_links_one_entry_per_event_and_keeps_every_article() -> None:
    events = DigestStore()
    events.persist(
        date=DIGEST_DATE,
        window=window(),
        news_items=[official_announcement(), techcrunch_report(), ars_report()],
        github_projects=[],
    )

    assert [entry.id for entry in store.get_digest(DIGEST_DATE).news] == ["official"]
    assert events.last_event_stats.candidates == 3
    assert events.last_event_stats.merged == 2

    # Dedup only removes the link. Every article is still in the database, so a
    # detail page and a later re-cluster still have the raw rows.
    session = new_session()
    try:
        repository = NewsRepository(session)
        for news_id in ("official", "media", "ars"):
            assert repository.get(news_id) is not None
    finally:
        session.close()


def test_persist_keeps_unrelated_news_alongside_a_merged_event() -> None:
    events = DigestStore()
    events.persist(
        date=DIGEST_DATE,
        window=window(),
        news_items=[
            official_announcement(),
            techcrunch_report(),
            item("nvidia", source="NVIDIA", title="NVIDIA opens robotics lab in Tokyo"),
        ],
        github_projects=[],
    )

    assert [entry.id for entry in store.get_digest(DIGEST_DATE).news] == [
        "official",
        "nvidia",
    ]


def test_a_second_refresh_does_not_reintroduce_a_merged_duplicate() -> None:
    """Merging runs over the whole linked set, not just this run's collection."""
    events = DigestStore()
    events.persist(
        date=DIGEST_DATE,
        window=window(),
        news_items=[official_announcement()],
        github_projects=[],
    )
    events.persist(
        date=DIGEST_DATE,
        window=window(),
        news_items=[techcrunch_report()],
        github_projects=[],
    )

    assert [entry.id for entry in store.get_digest(DIGEST_DATE).news] == ["official"]
    assert events.last_event_stats.merged == 1


def test_repeated_refresh_is_idempotent() -> None:
    events = DigestStore()
    for _ in range(3):
        events.persist(
            date=DIGEST_DATE,
            window=window(),
            news_items=[official_announcement(), techcrunch_report(), ars_report()],
            github_projects=[],
        )

    news_ids = [entry.id for entry in store.get_digest(DIGEST_DATE).news]
    assert news_ids == ["official"]
    assert events.last_event_stats.merged == 2


def test_persist_never_touches_a_news_row() -> None:
    """Folding a duplicate must not delete or rewrite the article itself."""
    events = DigestStore()
    events.persist(
        date=DIGEST_DATE,
        window=window(),
        news_items=[official_announcement(), techcrunch_report()],
        github_projects=[],
    )

    stored = store.get_news("media")
    assert stored is not None
    # Its own title and source survive untouched, which is what a detail page
    # and a future re-cluster need.
    assert stored.source == "TechCrunch AI"
    assert stored.title_original == "OpenAI launches GPT-6 Astra, a new frontier model"


# --- end to end through a refresh ---


def build_feed(entries: list[tuple[str, str, datetime, str]]) -> str:
    """A minimal RSS feed of (title, url, published_at, description) tuples."""
    items = "\n".join(
        f"    <item>\n"
        f"      <title>{title}</title>\n"
        f"      <link>{url}</link>\n"
        f"      <guid isPermaLink=\"true\">{url}</guid>\n"
        f"      <pubDate>{format_datetime(published)}</pubDate>\n"
        f"      <description>{description}</description>\n"
        f"    </item>"
        for title, url, published, description in entries
    )
    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        "<rss version=\"2.0\">\n"
        "  <channel>\n"
        "    <title>Test Feed</title>\n"
        f"{items}\n"
        "  </channel>\n"
        "</rss>\n"
    )


# One release reported by three outlets. Each report has its own slug so a test
# can place the same story on two different days without sharing a news_id.
ENRICHED_SUMMARY = "OpenAI 发布 GPT-6 Astra，面向长周期智能体任务与企业级场景。"


@dataclass(frozen=True)
class Report:
    source_id: str
    feed_url: str
    title: str
    body: str
    url: str


def reports_for(slug: str) -> list[Report]:
    """The same three reports of one release, under a per-day URL slug."""
    return [
        Report(
            source_id="openai",
            feed_url="https://openai.com/news/rss.xml",
            title=ANNOUNCEMENT,
            body=(
                "A new frontier model for long-horizon agentic work and enterprise "
                "tasks, available today in the API."
            ),
            url=f"https://openai.com/index/{slug}",
        ),
        Report(
            source_id="techcrunch-ai",
            feed_url="https://techcrunch.com/category/artificial-intelligence/feed/",
            title="OpenAI launches GPT-6 Astra, a new frontier model",
            body=(
                "A new frontier model for long-horizon agentic work and enterprise "
                "tasks is available today."
            ),
            url=f"https://techcrunch.com/2026/09/13/{slug}",
        ),
        Report(
            source_id="ars",
            feed_url="https://arstechnica.com/ai/feed/",
            title="OpenAI 发布 GPT-6 Astra，面向企业长任务",
            body="新模型面向企业长任务与 agentic 工作。",
            url=f"https://arstechnica.com/ai/2026/09/{slug}",
        ),
    ]


def seed_llm_cache(reports: list[Report], cache_dir, monkeypatch) -> None:
    """Pretend the LLM already summarised these articles into Chinese.

    Enrichment is off in tests, but a cached result is still read. Production
    summaries are Chinese for every source, which is what lets a Chinese report
    and an English announcement look alike, so seeding the cache exercises the
    real cross-language merge without a network call.
    """
    monkeypatch.setenv("LLM_CACHE_DIR", str(cache_dir))
    from app.pipelines.urls import canonicalize_url
    from app.services.llm.cache import LLMCache
    from app.services.llm.prompts import PROMPT_VERSION
    from app.services.llm.schemas import ArticleEnrichment
    from app.services.llm.settings import load_llm_settings

    settings = load_llm_settings()
    cache = LLMCache(settings.cache_dir)
    for report in reports:
        key = cache.make_key(
            canonical_url=canonicalize_url(report.url),
            title=report.title,
            summary=report.body,
            model=settings.model,
            prompt_version=PROMPT_VERSION,
        )
        cache.set(
            key,
            ArticleEnrichment(
                title_cn=ANNOUNCEMENT_CN,
                summary_cn=ENRICHED_SUMMARY,
                why_it_matters="",
                importance_score=88,
            ),
        )


def event_fetch(
    reports: list[Report],
    *,
    stamp: datetime,
    failing: set[str] | None = None,
):
    """One feed per source carrying that source's report of the release.

    Every other enabled source serves an empty page of its own shape, so nothing
    fails and nothing extra appears in the digest.
    """
    offline = failing or set()
    feeds: dict[str, tuple[str, str]] = {}
    for offset, report in enumerate(reports):
        feed = build_feed(
            [
                (
                    report.title,
                    report.url,
                    stamp + timedelta(hours=offset * 2),
                    report.body,
                )
            ]
        )
        feeds[report.feed_url] = (report.source_id, feed)

    def fetch(url: str, timeout: float = 10.0) -> str:
        route = feeds.get(url) or feeds.get(url.rstrip("/")) or feeds.get(url + "/")
        if route is None:
            source_id, payload = _empty_route_for(url)
        else:
            source_id, payload = route
        if source_id in offline:
            raise RuntimeError(f"{source_id} offline")
        return payload

    return fetch


def _empty_route_for(url: str) -> tuple[str, str]:
    """An empty payload for whichever enabled source owns ``url``."""
    for source in enabled_sources():
        if source.url.rstrip("/") == url.rstrip("/"):
            return source.id, _empty_payload(source.id, source.kind)
    # DeepSeek reads its listing from a second page whose URL is only known
    # after the index is parsed, so every further DeepSeek URL shares one page.
    if url.startswith("https://api-docs.deepseek.com/"):
        return "deepseek", EMPTY_HTML["deepseek"]
    return "", EMPTY_RSS


def _empty_payload(source_id: str, kind: str) -> str:
    if kind == "html":
        return EMPTY_HTML.get(source_id, f"<html><body><p>{source_id}</p></body></html>")
    return EMPTY_RSS


def test_refresh_folds_cross_source_duplicates_into_one_digest_entry(tmp_path, monkeypatch) -> None:
    """The whole production path: collect, enrich, window, dedupe, link."""
    reports = reports_for("gpt-6-astra")
    seed_llm_cache(reports, tmp_path / "llm-cache", monkeypatch)

    events = DigestStore()
    events.refresh(
        now=WINDOW_END,
        fetch_text=event_fetch(reports, stamp=datetime(2026, 9, 13, 6, 0, tzinfo=UTC)),
    )

    digest = store.get_digest(DIGEST_DATE)
    # One event, one entry: the official announcement.
    assert [entry.source for entry in digest.news] == ["OpenAI"]
    assert digest.news[0].title_cn == ANNOUNCEMENT_CN
    assert events.last_event_stats.candidates == 3
    assert events.last_event_stats.clusters == 1
    assert events.last_event_stats.merged == 2


def test_one_failing_source_does_not_stop_event_dedup(tmp_path, monkeypatch) -> None:
    """A source outage must not change how the surviving reports are merged."""
    reports = reports_for("gpt-6-astra")
    seed_llm_cache(reports, tmp_path / "llm-cache", monkeypatch)

    events = DigestStore()
    fetch = event_fetch(
        reports, stamp=datetime(2026, 9, 13, 6, 0, tzinfo=UTC), failing={"kimi"}
    )
    reports_seen = events.refresh(now=WINDOW_END, fetch_text=fetch)

    by_id = {report.source_id: report for report in reports_seen}
    assert by_id["kimi"].success is False
    assert by_id["kimi"].error
    assert by_id["openai"].success is True
    assert [entry.source for entry in store.get_digest(DIGEST_DATE).news] == ["OpenAI"]
    assert events.last_event_stats.merged == 2


def test_adjacent_refreshes_do_not_share_a_news_id(tmp_path, monkeypatch) -> None:
    """Event dedup must not reach across the issue window."""
    first_end = datetime(2026, 9, 12, 16, 0, tzinfo=UTC)
    day_one = reports_for("astra-day-one")
    day_two = reports_for("astra-day-two")
    seed_llm_cache(day_one + day_two, tmp_path / "llm-cache", monkeypatch)

    # Day one's three reports share the first window; day two's share the next,
    # so any id appearing in both would mean event dedup crossed the boundary.
    inside_day_one = "2026-09-12T10:00:00+00:00"
    events = DigestStore()
    events.persist(
        date="2026-09-13",
        window=DigestWindow(start=first_end - timedelta(hours=24), end=first_end),
        news_items=[
            entry.model_copy(update={"published_at": inside_day_one})
            for entry in (
                official_announcement(),
                techcrunch_report(),
                ars_report(),
            )
        ],
        github_projects=[],
    )
    events.refresh(
        now=WINDOW_END,
        fetch_text=event_fetch(day_two, stamp=datetime(2026, 9, 13, 6, 0, tzinfo=UTC)),
    )

    earlier = {entry.id for entry in store.get_digest("2026-09-13").news}
    later = {entry.id for entry in store.get_digest(DIGEST_DATE).news}
    assert earlier
    assert later
    assert earlier & later == set()


# --- settings ---


def test_thresholds_live_in_one_place() -> None:
    """Every threshold is a field, so a change is one visible edit."""
    settings = DEFAULT_SETTINGS
    assert 0 < settings.title_min_with_shared_term < settings.title_min <= 1
    assert settings.title_min <= settings.title_exact_threshold <= 1
    assert settings.body_min_with_shared_figure < settings.body_min <= 1
    assert settings.title_min < settings.title_relaxed_min <= 1
    assert settings.max_hours_apart > 0


@pytest.mark.parametrize("reverse", [False, True])
def test_output_order_is_independent_of_input_order(reverse: bool) -> None:
    items = [official_announcement(), techcrunch_report(), ars_report()]
    ordered = list(reversed(items)) if reverse else items

    kept, stats = dedupe_events(ordered)

    assert [entry.id for entry in kept] == ["official"]
    assert stats.merged == 2
