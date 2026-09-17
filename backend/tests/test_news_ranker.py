"""Phase 10.6: deterministic ranking, soft diversity, and Top Stories.

The ranker decides reading order, so the tests come in two halves: the score
itself (which signals move a story, and by how much) and the diversity pass
(which may reorder but must never drop). Both halves assert the same two
invariants — determinism and non-destruction — because those are what make the
feature safe to run on every refresh.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.config.ranking import DEFAULT_TOP_STORY_LIMIT
from app.models import NewsCategory, NewsItem
from app.services.article_extractor import METHOD_RSS_SUMMARY, METHOD_WEB
from app.services.news_ranker import (
    RankingSettings,
    rank_news,
)
from app.services.news_topics import (
    TOPIC_AGENT,
    TOPIC_BUSINESS,
    TOPIC_HARDWARE,
    TOPIC_MODEL_RELEASE,
    TOPIC_OPEN_SOURCE,
    TOPIC_OTHER,
    TOPIC_POLICY,
    TOPIC_RESEARCH,
    detect_company,
    detect_topic,
)

UTC = timezone.utc

# A one-day window, so recency has a fixed span to interpolate across.
WINDOW_START = datetime(2026, 9, 12, 16, 0, tzinfo=UTC)
WINDOW_END = datetime(2026, 9, 13, 16, 0, tzinfo=UTC)
WINDOW_MIDDLE = WINDOW_START + timedelta(hours=12)


def news(
    news_id: str,
    *,
    title: str = "A story",
    source: str = "OpenAI",
    source_type: str = "official",
    importance: int | None = 50,
    published: datetime | None = None,
    method: str = METHOD_WEB,
    body: str = "Body text.",
) -> NewsItem:
    moment = published or WINDOW_MIDDLE
    return NewsItem(
        id=news_id,
        title_cn=title,
        title_original=title,
        summary="摘要",
        why_it_matters="",
        source=source,
        source_type=source_type,
        published_at=moment.isoformat(),
        category=NewsCategory.highlight,
        tags=[source],
        url=f"https://example.com/{news_id}",
        importance_score=importance,
        content_original=body,
        content_extraction_method=method,
    )


def order(items: list[NewsItem], **kwargs) -> list[str]:
    ranked, _stats = rank_news(
        items, window_start=WINDOW_START, window_end=WINDOW_END, **kwargs
    )
    return [entry.news_id for entry in ranked]


# --- score composition ---


def test_higher_importance_ranks_first() -> None:
    """importance is the dominant signal, all else equal."""
    items = [
        news("low", importance=20),
        news("high", importance=95),
        news("mid", importance=55),
    ]

    assert order(items) == ["high", "mid", "low"]


def test_official_source_outranks_media_at_equal_importance() -> None:
    items = [
        news("media", source="TechCrunch AI", source_type="media", importance=70),
        news("official", source="OpenAI", source_type="official", importance=70),
    ]

    assert order(items) == ["official", "media"]


def test_big_media_story_can_be_outranked_by_nothing_but_importance() -> None:
    """A media scoop may lead a minor official post: source is a weight, not a gate."""
    items = [
        news("minor-official", source="OpenAI", source_type="official", importance=25),
        news("big-media", source="TechCrunch AI", source_type="media", importance=95),
    ]

    assert order(items) == ["big-media", "minor-official"]


def test_research_outranks_media_at_equal_importance() -> None:
    """The tier order is official > research > media, not official > media."""
    items = [
        news("media", source="Ars Technica", source_type="media", importance=70),
        news("research", source="Hugging Face", source_type="research", importance=70),
    ]

    assert order(items) == ["research", "media"]


def test_every_configured_source_type_has_a_weight() -> None:
    """No configured source class may fall through to the unknown weight.

    Phase 10.11 renamed ``blog`` to ``research``; the weight table kept the old
    key, which silently demoted both research sources below the press. Tying the
    table to ``NEWS_SOURCE_TYPES`` makes that class of rename fail a test instead
    of quietly reordering the digest.
    """
    from app.config.sources import NEWS_SOURCE_TYPES
    from app.services.news_ranker import SOURCE_TYPE_RANKS

    missing = [name for name in NEWS_SOURCE_TYPES if name not in SOURCE_TYPE_RANKS]
    assert missing == []
    assert SOURCE_TYPE_RANKS["official"] > SOURCE_TYPE_RANKS["research"]
    assert SOURCE_TYPE_RANKS["research"] > SOURCE_TYPE_RANKS["media"]


def test_source_class_orders_equal_stories_official_then_research_then_media() -> None:
    """Phase 10.13: at equal importance the class order is unambiguous."""
    items = [
        news("media", source="TechCrunch AI", source_type="media", importance=70),
        news("research", source="Hugging Face", source_type="research", importance=70),
        news("official", source="OpenAI", source_type="official", importance=70),
    ]

    assert order(items) == ["official", "research", "media"]
    # Order of input must not decide it.
    assert order(list(reversed(items))) == ["official", "research", "media"]


def test_source_class_gap_is_wide_enough_to_be_visible() -> None:
    """The class has to move the score, not merely break an exact tie.

    Phase 10.13 raised ``source_weight`` because the previous gap was small
    enough to be swallowed by a one-point importance difference, which made the
    stated priority order effectively decorative.
    """
    settings = RankingSettings()
    item = news("official", source_type="official", importance=70)
    media = news("media", source="TechCrunch AI", source_type="media", importance=70)
    ranked, _stats = rank_news(
        [item, media], window_start=WINDOW_START, window_end=WINDOW_END, settings=settings
    )
    gap = ranked[0].rank_score - ranked[1].rank_score
    from app.services.news_ranker import SOURCE_TYPE_RANKS

    expected = (
        (SOURCE_TYPE_RANKS["official"] - SOURCE_TYPE_RANKS["media"])
        * settings.source_weight
        * 100.0
    )
    assert gap == pytest.approx(expected, abs=0.01)
    # A whole class step is worth several importance points, so a story cannot
    # outrank across classes on a one-point difference alone.
    assert gap > 100.0 * settings.importance_weight * 0.10


def test_source_class_still_cannot_override_a_large_importance_gap() -> None:
    """It stays a weight: a huge media story still leads a routine vendor note."""
    items = [
        news("big-media", source="TechCrunch AI", source_type="media", importance=95),
        news("minor-official", source="OpenAI", source_type="official", importance=20),
    ]

    assert order(items) == ["big-media", "minor-official"]


def test_source_class_gap_does_not_swallow_a_real_importance_difference() -> None:
    """A clearly bigger story wins whatever class it came from.

    This is the property the widened weight must not break: the largest class
    step must stay smaller than an importance gap of 30 points, which is the
    scale at which two stories are describing genuinely different things. The
    class can reorder comparable stories (what Phase 10.13 asks for) but not
    overturn a clear importance difference.
    """
    settings = RankingSettings()
    from app.services.news_ranker import SOURCE_TYPE_RANKS

    largest_class_step = (
        (SOURCE_TYPE_RANKS["official"] - SOURCE_TYPE_RANKS["media"])
        * settings.source_weight
        * 100.0
    )
    assert largest_class_step < 100.0 * settings.importance_weight * 0.30

    # With the shipped numbers the crossover sits just under 30 points: a media
    # story 20 points ahead still loses to the vendor, one 50 points ahead wins.
    # Stated as round numbers so a future rebalance moves the assertion rather
    # than breaking it on a rounding boundary.
    below = [
        news("media", source="TechCrunch AI", source_type="media", importance=60),
        news("official", source="OpenAI", source_type="official", importance=40),
    ]
    assert order(below) == ["official", "media"]
    above = [
        news("media", source="TechCrunch AI", source_type="media", importance=90),
        news("official", source="OpenAI", source_type="official", importance=40),
    ]
    assert order(above) == ["media", "official"]


def test_content_quality_is_a_weak_signal() -> None:
    """A full body beats a feed teaser, but only by a little."""
    items = [
        news(
            "fallback",
            title="Vendor one ships a tool",
            source="Source A",
            method=METHOD_RSS_SUMMARY,
            importance=70,
            body="teaser",
        ),
        news(
            "full",
            title="Vendor two ships a tool",
            source="Source B",
            method=METHOD_WEB,
            importance=70,
            body="a" * 4000,
        ),
    ]
    ranked, _stats = rank_news(items, window_start=WINDOW_START, window_end=WINDOW_END)

    assert [entry.news_id for entry in ranked] == ["full", "fallback"]
    gap = ranked[0].rank_score - ranked[1].rank_score
    # The whole content weight is 6 points, so even a full body cannot open a
    # large gap against a story with the same importance.
    assert gap < 6.0


def test_rss_fallback_story_can_still_rank_first() -> None:
    """Having no extracted body must not bury a genuinely important story."""
    items = [
        news("important-teaser", method=METHOD_RSS_SUMMARY, importance=98, body="短"),
        news("routine-full", method=METHOD_WEB, importance=40, body="b" * 4000),
    ]

    assert order(items) == ["important-teaser", "routine-full"]


def test_long_body_is_not_automatically_more_important() -> None:
    """Length saturates, so a much longer body does not keep climbing."""
    items = [
        news(
            "short",
            title="Vendor one ships a tool",
            source="Source A",
            method=METHOD_WEB,
            importance=60,
            body="a" * 2000,
        ),
        news(
            "very-long",
            title="Vendor two ships a tool",
            source="Source B",
            method=METHOD_WEB,
            importance=60,
            body="a" * 60000,
        ),
    ]
    ranked, _stats = rank_news(items, window_start=WINDOW_START, window_end=WINDOW_END)

    # Saturating the length signal caps what size alone can buy: 30x the text
    # moves the score by well under the 6-point content weight.
    assert abs(ranked[0].rank_score - ranked[1].rank_score) < 2.0


def test_recency_never_overrides_a_large_importance_gap() -> None:
    items = [
        news("old-but-huge", importance=99, published=WINDOW_START + timedelta(minutes=1)),
        news("new-but-small", importance=20, published=WINDOW_END - timedelta(minutes=1)),
    ]

    assert order(items) == ["old-but-huge", "new-but-small"]


def test_recency_breaks_a_tie_between_equal_stories() -> None:
    items = [
        news("older", importance=70, published=WINDOW_START + timedelta(hours=1)),
        news("newer", importance=70, published=WINDOW_END - timedelta(hours=1)),
    ]

    assert order(items) == ["newer", "older"]


def test_multi_source_cluster_earns_a_small_bonus() -> None:
    items = [
        news("corroborated", title="Vendor one ships a tool", source="Source A", importance=60),
        news("single", title="Vendor two ships a tool", source="Source B", importance=60),
    ]
    ranked, _stats = rank_news(
        items,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        cluster_sizes={"corroborated": 3},
    )

    assert [entry.news_id for entry in ranked] == ["corroborated", "single"]
    assert ranked[0].rank_components.cluster > 0


def test_cluster_bonus_is_capped() -> None:
    """Ten outlets reporting one story must not out-rank a far bigger one."""
    items = [news("everywhere", importance=50), news("huge", importance=95)]
    ranked, _stats = rank_news(
        items,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        cluster_sizes={"everywhere": 11, "huge": 1},
    )

    assert [entry.news_id for entry in ranked] == ["huge", "everywhere"]


def test_missing_importance_is_treated_as_neutral_not_zero() -> None:
    """An un-enriched article must not lead, but must not be punished either."""
    items = [
        news("unknown", importance=None),
        news("strong", importance=85),
        news("weak", importance=15),
    ]

    assert order(items) == ["strong", "unknown", "weak"]


# --- diversity reranking ---


def test_repeated_company_yields_to_a_different_company() -> None:
    """Several OpenAI stories in a row let a comparable rival through."""
    openai_run = [
        news(f"openai-{index}", title=f"OpenAI ships update {index}", importance=90)
        for index in range(1, 5)
    ]
    rival = news(
        "anthropic",
        title="Anthropic ships a Claude update",
        source="Anthropic",
        importance=86,
    )

    ranked, _stats = rank_news(
        openai_run + [rival], window_start=WINDOW_START, window_end=WINDOW_END
    )
    ids = [entry.news_id for entry in ranked]

    # The rival is slightly weaker but a different company, so it is promoted
    # above at least one of the OpenAI run.
    assert ids.index("anthropic") < ids.index("openai-4")


def test_three_genuinely_big_openai_stories_all_stay_in_top_stories() -> None:
    """A soft penalty must not evict real news from the top of the digest."""
    dominant = [
        news(f"openai-{index}", title=f"OpenAI announces GPT-{index}", importance=95)
        for index in range(1, 4)
    ]
    filler = [
        news(
            f"filler-{index}",
            title=f"Company {index} posts a note",
            source=f"Source {index}",
            source_type="media",
            importance=30,
        )
        for index in range(1, 10)
    ]

    ranked, stats = rank_news(
        dominant + filler, window_start=WINDOW_START, window_end=WINDOW_END
    )
    top_ids = [entry.news_id for entry in ranked if entry.is_top_story]

    assert stats.top_stories == DEFAULT_TOP_STORY_LIMIT
    assert {"openai-1", "openai-2", "openai-3"} <= set(top_ids)


def test_diversity_penalty_never_removes_a_story() -> None:
    """Every candidate is still ranked, even the ones the penalty pushed down."""
    items = [
        news(f"openai-{index}", title="OpenAI announces a model", importance=90)
        for index in range(1, 8)
    ]
    ranked, stats = rank_news(
        items, window_start=WINDOW_START, window_end=WINDOW_END
    )

    assert len(ranked) == len(items)
    assert {entry.news_id for entry in ranked} == {item.id for item in items}
    assert stats.candidates == len(items)


def test_same_topic_run_is_penalised() -> None:
    """Four model releases let a comparable research story through."""
    releases = [
        news(
            f"release-{index}",
            title=f"Vendor {index} launches a new model",
            source=f"Outlet {index}",
            importance=88,
        )
        for index in range(1, 5)
    ]
    research = news(
        "research",
        title="A new interpretability research paper",
        source="Research Desk",
        importance=86,
    )

    ranked, _stats = rank_news(
        releases + [research], window_start=WINDOW_START, window_end=WINDOW_END
    )
    ids = [entry.news_id for entry in ranked]

    # The research story is slightly weaker but a different topic, so it is
    # promoted above the last of the release run.
    assert ids.index("research") < ids.index("release-4")


def test_same_source_run_is_penalised() -> None:
    from_one = [
        news(f"same-{index}", title=f"Note {index}", source="NVIDIA", importance=80)
        for index in range(1, 5)
    ]
    other = news("other", title="Note from elsewhere", source="Anthropic", importance=77)

    ranked, _stats = rank_news(
        from_one + [other], window_start=WINDOW_START, window_end=WINDOW_END
    )
    ids = [entry.news_id for entry in ranked]

    assert ids.index("other") < ids.index("same-4")


def test_diversity_penalty_is_bounded_so_a_weak_story_cannot_lead() -> None:
    """Five OpenAI giants must still beat an irrelevant note from elsewhere."""
    giants = [
        news(f"giant-{index}", title="OpenAI announces a frontier model", importance=97)
        for index in range(1, 6)
    ]
    trivial = news(
        "trivial",
        title="A small studio notes a tip",
        source="Tiny Blog",
        source_type="media",
        importance=5,
    )

    ranked, _stats = rank_news(
        giants + [trivial], window_start=WINDOW_START, window_end=WINDOW_END
    )

    assert ranked[0].news_id.startswith("giant-")
    assert ranked[-1].news_id == "trivial"


def test_diversity_never_demotes_a_much_more_important_story() -> None:
    """A crowded beat may reorder peers, never bury a clearly bigger story.

    Real data surfaced this: with the penalty set too high, an importance-88
    story sank below a 72 for no reason other than arriving after a run from the
    same source. The cap keeps the worst case inside one importance band.

    Both sides are the same source class on purpose. Source class is a separate,
    much larger signal (Phase 10.13 widened it to 17 points between official and
    media), so a media story here would be testing that weight rather than the
    diversity penalty this case is about. Comparison of the classes is covered
    by the source-priority tests above.
    """
    crowd = [
        news(f"crowd-{index}", title=f"Note {index}", importance=70)
        for index in range(1, 13)
    ]
    major = news(
        "major",
        title="A landmark model release",
        source="Another Outlet",
        importance=88,
    )
    ranked, _stats = rank_news(
        crowd + [major], window_start=WINDOW_START, window_end=WINDOW_END
    )
    ids = [entry.news_id for entry in ranked]

    # Nothing except the leader may sit above a story 18 importance points up.
    assert ids.index("major") <= 1


def test_rank_score_never_rises_further_down_the_digest() -> None:
    """Every position is chosen the same way, so the stored scores stay ordered.

    A greedy pass that stopped at the top-story boundary would leave the tail in
    raw base-score order, and a tail entry could then outscore the one above it.
    """
    items = [
        news(f"openai-{index}", title="OpenAI announces a model", importance=90 - index)
        for index in range(1, 13)
    ] + [
        news(
            f"other-{index}",
            title=f"Vendor {index} notes something",
            source=f"Source {index}",
            source_type="media",
            importance=85 - index,
        )
        for index in range(1, 6)
    ]
    ranked, _stats = rank_news(
        items,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        settings=RankingSettings(top_story_limit=3),
    )
    scores = [entry.rank_score for entry in ranked]

    assert scores == sorted(scores, reverse=True)


# --- determinism and tie breaking ---


def test_ranking_is_deterministic_across_input_order() -> None:
    items = [
        news("a", importance=70),
        news("b", importance=70),
        news("c", importance=70),
        news("d", importance=70),
    ]

    assert order(items) == order(list(reversed(items)))


def test_ranking_is_deterministic_across_repeated_runs() -> None:
    items = [news(f"n-{index}", importance=50 + index) for index in range(1, 10)]
    first = [entry.describe() for entry in rank_news(items)[0]]
    second = [entry.describe() for entry in rank_news(items)[0]]

    assert first == second


def test_tie_break_uses_published_at_then_id() -> None:
    """Two identical stories are separated by time, then by a stable id."""
    same_time = WINDOW_MIDDLE
    items = [
        news("zzz", importance=60, published=same_time),
        news("aaa", importance=60, published=same_time),
        news("newest", importance=60, published=same_time + timedelta(hours=1)),
    ]

    assert order(items) == ["newest", "aaa", "zzz"]


def test_rank_numbers_are_contiguous_from_one() -> None:
    items = [news(f"n-{index}") for index in range(1, 6)]
    ranked, _stats = rank_news(items, window_start=WINDOW_START, window_end=WINDOW_END)

    assert [entry.rank for entry in ranked] == [1, 2, 3, 4, 5]


# --- top stories ---


def test_top_story_limit_marks_exactly_the_leading_stories() -> None:
    items = [news(f"n-{index}", importance=100 - index) for index in range(1, 16)]
    ranked, stats = rank_news(
        items,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        settings=RankingSettings(top_story_limit=4),
    )

    assert stats.top_stories == 4
    assert [entry.is_top_story for entry in ranked] == [True] * 4 + [False] * 11


def test_short_digest_marks_every_story_as_top() -> None:
    items = [news("only", importance=50), news("second", importance=40)]
    ranked, stats = rank_news(
        items,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        settings=RankingSettings(top_story_limit=10),
    )

    assert stats.top_stories == 2
    assert all(entry.is_top_story for entry in ranked)


def test_zero_top_story_limit_still_ranks_everything() -> None:
    items = [news("a", importance=50), news("b", importance=40)]
    ranked, stats = rank_news(
        items,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        settings=RankingSettings(top_story_limit=0),
    )

    assert stats.top_stories == 0
    assert [entry.news_id for entry in ranked] == ["a", "b"]
    assert not any(entry.is_top_story for entry in ranked)


def test_empty_input_produces_no_ranking() -> None:
    ranked, stats = rank_news([])

    assert ranked == []
    assert stats.candidates == 0


# --- rank reason and components ---


def test_rank_reason_names_the_signals_that_mattered() -> None:
    items = [
        news(
            "big",
            title="OpenAI launches GPT-9",
            importance=95,
            body="a" * 4000,
        )
    ]
    ranked, _stats = rank_news(items, window_start=WINDOW_START, window_end=WINDOW_END)
    reason = ranked[0].rank_reason

    assert "high importance" in reason
    assert "official source" in reason
    assert "full text" in reason
    assert "OpenAI" in reason


def test_rank_components_expose_each_contribution() -> None:
    items = [news("a", importance=80)]
    ranked, _stats = rank_news(items, window_start=WINDOW_START, window_end=WINDOW_END)
    described = ranked[0].describe()

    for field in ("importance=", "source=", "recency=", "content=", "cluster=", "diversity="):
        assert field in described


def test_top_story_scores_are_ordered_descending_after_diversity() -> None:
    """The promoted story's score reflects the penalty, so the list stays sorted."""
    items = [
        news("openai-1", title="OpenAI announces a model", importance=90),
        news("openai-2", title="OpenAI announces a model", importance=90),
        news(
            "anthropic",
            title="Anthropic announces a model",
            source="Anthropic",
            importance=88,
        ),
    ]
    ranked, _stats = rank_news(items, window_start=WINDOW_START, window_end=WINDOW_END)

    assert [entry.news_id for entry in ranked] == ["openai-1", "anthropic", "openai-2"]
    # The demoted OpenAI entry carries a negative diversity component.
    assert ranked[2].rank_components.diversity < 0


def test_window_is_optional_and_ranking_still_works() -> None:
    """A rebuild without a window drops recency instead of guessing."""
    items = [news("a", importance=90), news("b", importance=20)]
    ranked, _stats = rank_news(items)

    assert [entry.news_id for entry in ranked] == ["a", "b"]
    assert ranked[0].rank_components.recency == 0.0


# --- topic and company detection ---


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("OpenAI launches GPT-7", TOPIC_MODEL_RELEASE),
        ("A new agent framework for tool calling", TOPIC_AGENT),
        ("Interpretability research paper published", TOPIC_RESEARCH),
        ("Model weights are now open source on Hugging Face", TOPIC_OPEN_SOURCE),
        ("New developer SDK and API for builders", "developer_tools"),
        ("NVIDIA announces a new GPU chip", TOPIC_HARDWARE),
        ("Startup raised a 500M funding round", TOPIC_BUSINESS),
        ("EU regulators open an antitrust investigation", TOPIC_POLICY),
        ("A completely unrelated sentence about weather", TOPIC_OTHER),
    ],
)
def test_topic_detection(title: str, expected: str) -> None:
    """The first matching rule wins, so specific topics run before general ones."""
    assert detect_topic(title) == expected


def test_policy_outranks_business_and_hardware() -> None:
    """"chip export ban" is regulation, not a chip launch or a market story."""
    assert detect_topic("New chip export ban announced for AI accelerators") == TOPIC_POLICY


def test_model_release_wins_over_the_generic_word_model() -> None:
    assert detect_topic("Meta releases Llama 5 weights") == TOPIC_MODEL_RELEASE


def test_topic_detection_falls_back_to_other() -> None:
    assert detect_topic("") == TOPIC_OTHER
    assert detect_topic(None) == TOPIC_OTHER


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("OpenAI ships GPT-7", "OpenAI"),
        ("Anthropic updates Claude", "Anthropic"),
        ("Google DeepMind publishes a Gemini report", "Google DeepMind"),
        ("Meta open sources Llama", "Meta"),
        ("NVIDIA reports record data center revenue", "NVIDIA"),
        ("DeepSeek releases a new model", "DeepSeek"),
        ("Qwen adds a new size", "Alibaba Qwen"),
        ("Kimi announces a long context update", "Moonshot Kimi"),
        ("A new dataset on Hugging Face", "Hugging Face"),
        ("A story with no company at all", ""),
    ],
)
def test_company_detection(text: str, expected: str) -> None:
    assert detect_company(text) == expected


def test_latin_keywords_match_whole_words_only() -> None:
    """"meta" must not fire inside "metadata", nor "api" inside "capital"."""
    assert detect_company("A metadata schema for pipelines") == ""
    assert detect_topic("Capital allocation in the industry") == TOPIC_OTHER


def test_company_is_read_from_the_source_name_too() -> None:
    """"量子位" reports on DeepSeek; the byline is the only company evidence."""
    assert detect_company("量子位", "深度求索发布新模型") == "DeepSeek"


def test_ranker_labels_each_story() -> None:
    items = [
        news("a", title="OpenAI launches GPT-7", importance=50),
        news("b", title="NVIDIA announces a GPU", source="NVIDIA", importance=50),
    ]
    ranked, stats = rank_news(items, window_start=WINDOW_START, window_end=WINDOW_END)
    by_id = {entry.news_id: entry for entry in ranked}

    assert by_id["a"].company == "OpenAI"
    assert by_id["a"].topic == TOPIC_MODEL_RELEASE
    assert by_id["b"].company == "NVIDIA"
    assert by_id["b"].topic == TOPIC_HARDWARE
    assert stats.companies == 2


# --- settings ---


def test_every_threshold_lives_in_settings() -> None:
    settings = RankingSettings()

    assert settings.top_story_limit == DEFAULT_TOP_STORY_LIMIT
    assert settings.company_repeat_penalty > 0
    assert settings.topic_repeat_penalty > 0
    assert settings.source_repeat_penalty > 0
    # The component weights leave room for the cluster bonus without any single
    # one of them dominating the score outright.
    assert settings.importance_weight > settings.source_weight
    assert sum(
        (
            settings.importance_weight,
            settings.source_weight,
            settings.recency_weight,
            settings.content_weight,
        )
    ) <= 1.0
