"""Phase 10.13: keeping second-hand reporting to a curated few.

The rules are counted rather than judged, so each case here states its input and
the exact number that may survive. Two properties matter beyond the counts:
official and research are never capped, and nothing is deleted — a dropped
article is simply not linked, so it stays stored and stays searchable.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models import NewsCategory, NewsItem
from app.services.digest_store import DigestStore, store
from app.services.digest_window import DigestWindow
from app.services.event_dedup import dedupe_events
from app.services.media_selection import (
    DEFAULT_SETTINGS,
    REASON_MISSING_IMPORTANCE,
    REASON_PER_SOURCE_CAP,
    REASON_TOTAL_CAP,
    MediaSelectionSettings,
    format_media_selection,
    select_media_articles,
)

UTC = timezone.utc

WINDOW_START = datetime(2026, 9, 12, 16, 0, tzinfo=UTC)
WINDOW_END = datetime(2026, 9, 13, 16, 0, tzinfo=UTC)
DIGEST_DATE = "2026-09-13"


def article(
    news_id: str,
    *,
    source: str = "TechCrunch AI",
    source_type: str = "media",
    importance: int | None = 80,
    title: str = "A story",
    published: datetime | None = None,
) -> NewsItem:
    moment = published or WINDOW_END - timedelta(hours=1)
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
    )


def kept_ids(items: list[NewsItem], settings: MediaSelectionSettings = DEFAULT_SETTINGS) -> list[str]:
    selected, _stats = select_media_articles(items, settings)
    return [item.id for item in selected]


def window() -> DigestWindow:
    return DigestWindow(start=WINDOW_START, end=WINDOW_END)


# --- rule 1: importance threshold ---


def test_media_below_the_threshold_is_dropped() -> None:
    items = [article("low", importance=59), article("exact", importance=60)]

    assert kept_ids(items) == ["exact"]


def test_media_at_the_threshold_is_eligible() -> None:
    selected, stats = select_media_articles([article("exact", importance=60)])

    assert [item.id for item in selected] == ["exact"]
    assert stats.selected == 1
    assert stats.below_threshold == 0


def test_media_without_an_importance_score_is_not_eligible() -> None:
    """A fallback score is what the pipeline uses when it has no judgement."""
    selected, stats = select_media_articles([article("unknown", importance=None)])

    assert selected == []
    assert stats.below_threshold == 1
    assert stats.decisions[0].reason == REASON_MISSING_IMPORTANCE


def test_a_high_score_is_not_the_only_thing_that_matters() -> None:
    selected, stats = select_media_articles([article("low", importance=10)])

    assert selected == []
    assert stats.below_threshold == 1
    assert stats.decisions[0].reason == "importance<60"


# --- rule 2: per-digest total ---


def test_ten_eligible_media_stories_leave_at_most_five() -> None:
    items = [
        article(f"m{index}", source=f"Outlet {index}", importance=70 + index)
        for index in range(1, 11)
    ]

    selected, stats = select_media_articles(items)

    assert len(selected) == 5
    assert stats.dropped_total == 5
    # The strongest five are the ones that survive.
    assert {item.id for item in selected} == {"m6", "m7", "m8", "m9", "m10"}


def test_the_total_cap_keeps_the_most_important_not_the_first_seen() -> None:
    items = [
        article("weak", importance=61),
        article("strong", importance=99),
    ]
    settings = MediaSelectionSettings(max_total=1)

    assert kept_ids(items, settings) == ["strong"]


def test_total_cap_is_configurable() -> None:
    items = [article(f"m{index}", source=f"Outlet {index}") for index in range(1, 5)]

    assert len(kept_ids(items, MediaSelectionSettings(max_total=2))) == 2


def test_total_cap_never_exceeds_the_number_of_candidates() -> None:
    items = [article("only", importance=90)]

    assert kept_ids(items) == ["only"]


# --- rule 3: per-source cap ---


def test_one_busy_outlet_is_capped_even_when_it_dominates() -> None:
    """TechCrunch 5 + Ars 3: no outlet may take more than two slots."""
    items = [article(f"tc{index}", source="TechCrunch AI") for index in range(1, 6)] + [
        article(f"ars{index}", source="Ars Technica") for index in range(1, 4)
    ]

    selected, stats = select_media_articles(items)

    by_source: dict[str, int] = {}
    for item in selected:
        by_source[item.source] = by_source.get(item.source, 0) + 1
    assert by_source == {"TechCrunch AI": 2, "Ars Technica": 2}
    assert stats.dropped_per_source == 4
    assert stats.dropped_total == 0


def test_per_source_cap_applies_before_the_total_cap() -> None:
    """A capped outlet frees its slot for a different outlet, not for itself."""
    items = [article(f"tc{index}", source="TechCrunch AI") for index in range(1, 5)] + [
        article("other", source="Ars Technica")
    ]

    selected, stats = select_media_articles(items)

    assert {item.id for item in selected} == {"tc1", "tc2", "other"}
    assert stats.dropped_per_source == 2
    assert stats.dropped_total == 0


def test_per_source_cap_is_configurable() -> None:
    items = [article(f"tc{index}", source="TechCrunch AI") for index in range(1, 4)]

    assert len(kept_ids(items, MediaSelectionSettings(max_per_source=1))) == 1


# --- official and research are exempt ---


def test_official_sources_are_never_capped() -> None:
    items = [
        article(f"o{index}", source=f"Vendor {index}", source_type="official")
        for index in range(1, 21)
    ]

    selected, stats = select_media_articles(items)

    assert len(selected) == 20
    assert stats.candidates == 0
    assert stats.dropped == 0


def test_research_sources_are_never_capped() -> None:
    items = [
        article(f"r{index}", source="Hugging Face", source_type="research")
        for index in range(1, 21)
    ]

    selected, stats = select_media_articles(items)

    assert len(selected) == 20
    assert stats.candidates == 0


def test_official_is_exempt_even_from_its_own_source_cap() -> None:
    """The per-source cap is about outlets, not about a vendor's own blog."""
    items = [
        article(f"o{index}", source="OpenAI", source_type="official") for index in range(1, 6)
    ]

    assert len(kept_ids(items)) == 5


def test_an_unlisted_source_type_is_not_capped() -> None:
    """Only the ``media`` class is curated; anything else passes through."""
    items = [article(f"x{index}", source_type="unknown") for index in range(1, 8)]

    assert len(kept_ids(items)) == 7


# --- interaction with the pipeline ---


def test_only_media_is_removed_and_input_order_is_preserved() -> None:
    items = [
        article("official", source="OpenAI", source_type="official"),
        article("low", importance=10),
        article("media", importance=90),
        article("research", source="Hugging Face", source_type="research"),
    ]

    assert kept_ids(items) == ["official", "media", "research"]


def test_an_empty_digest_reports_no_candidates() -> None:
    selected, stats = select_media_articles([])

    assert selected == []
    assert stats.candidates == 0
    assert stats.selected == 0
    assert format_media_selection(stats).splitlines()[1] == "Candidates: 0"


def test_an_unreadable_publish_date_does_not_break_ordering() -> None:
    """A malformed timestamp sorts last instead of raising."""
    broken = article("broken", importance=80)
    broken = broken.model_copy(update={"published_at": "not-a-date"})
    fine = article("fine", importance=80)
    settings = MediaSelectionSettings(max_total=1)

    assert kept_ids([broken, fine], settings) == ["fine"]


def test_selection_is_deterministic_across_input_order() -> None:
    items = [article(f"m{index}", source=f"Outlet {index}", importance=60 + index) for index in range(1, 11)]

    # Output preserves the caller's order, so the *set* is what must not depend
    # on it: which stories survive is decided by the rules, not by collection.
    assert set(kept_ids(items)) == set(kept_ids(list(reversed(items))))


def test_recency_breaks_an_importance_tie() -> None:
    older = article("older", importance=80, published=WINDOW_START + timedelta(hours=1))
    newer = article("newer", importance=80, published=WINDOW_END - timedelta(hours=1))
    settings = MediaSelectionSettings(max_total=1)

    assert kept_ids([older, newer], settings) == ["newer"]


def test_an_event_official_already_reported_does_not_reach_selection() -> None:
    """Event dedup runs first, so the media duplicate is already folded away."""
    official = article(
        "official",
        source="OpenAI",
        source_type="official",
        importance=70,
        title="Introducing GPT-6 Astra",
    )
    media = article(
        "media",
        source="TechCrunch AI",
        importance=95,
        title="OpenAI launches GPT-6 Astra",
    )
    merged, _stats = dedupe_events([official, media])
    selected, selection = select_media_articles(merged)

    # The press report was folded into the vendor's own announcement, so it is
    # not a media candidate at all and cannot be re-added.
    assert [item.id for item in selected] == ["official"]
    assert selection.candidates == 0


def test_a_media_only_big_story_still_enters_the_digest() -> None:
    """A scoop nobody first-party covered is exactly what media is for."""
    items = [
        article("official", source="OpenAI", source_type="official", importance=40),
        article("scoop", source="TechCrunch AI", importance=90, title="OpenAI faces a probe"),
    ]

    assert kept_ids(items) == ["official", "scoop"]


# --- the debug view ---


def test_format_reports_every_count() -> None:
    items = [
        article(f"tc{index}", source="TechCrunch AI", importance=90) for index in range(1, 5)
    ] + [
        article("low", source="Ars Technica", importance=10),
        article("ars", source="Ars Technica", importance=88),
    ]

    _selected, stats = select_media_articles(items)
    rendered = format_media_selection(stats)

    assert "Media selection" in rendered
    assert "Candidates: 6" in rendered
    assert "Below importance threshold: 1" in rendered
    assert "Dropped by per-source cap: 2" in rendered
    assert "Dropped by total cap: 0" in rendered
    assert "Selected: 3" in rendered
    # The default view stays one summary block.
    assert "KEEP" not in rendered


def test_format_lists_each_decision_in_debug_mode() -> None:
    items = [
        article("keep", source="TechCrunch AI", importance=82, title="A launch"),
        article("capped", source="TechCrunch AI", importance=80, title="A second launch"),
        article("capped-3", source="TechCrunch AI", importance=78, title="A third launch"),
        article("dropped", source="Ars Technica", importance=59, title="A minor note"),
    ]

    _selected, stats = select_media_articles(items)
    rendered = format_media_selection(stats, debug=True)

    assert "KEEP TechCrunch AI | A launch | importance=82" in rendered
    assert "KEEP TechCrunch AI | A second launch | importance=80" in rendered
    assert "DROP TechCrunch AI | A third launch | reason=per_source_cap" in rendered
    assert "DROP Ars Technica | A minor note | reason=importance<60" in rendered


def test_a_recorded_decision_names_the_right_reason() -> None:
    items = [article(f"m{index}", source="Outlet", importance=90) for index in range(1, 5)]

    _selected, stats = select_media_articles(items)
    reasons = {decision.reason for decision in stats.decisions}

    assert REASON_PER_SOURCE_CAP in reasons


def test_the_total_cap_reason_is_distinguishable() -> None:
    items = [
        article(f"m{index}", source=f"Outlet {index}", importance=90 - index)
        for index in range(1, 8)
    ]

    _selected, stats = select_media_articles(items)

    assert stats.dropped_total == 2
    assert any(decision.reason == REASON_TOTAL_CAP for decision in stats.decisions)


# --- persistence: curation links fewer articles, deletes nothing ---


def test_persist_links_only_the_selected_media_and_keeps_every_row() -> None:
    events = DigestStore()
    items = [
        article("official", source="OpenAI", source_type="official"),
        article("low", source="Ars Technica", importance=10),
        *[article(f"tc{index}", source="TechCrunch AI", importance=90) for index in range(1, 5)],
    ]

    events.persist(
        date=DIGEST_DATE, window=window(), news_items=items, github_projects=[]
    )

    linked = [entry.id for entry in store.get_digest(DIGEST_DATE).news]
    assert "official" in linked
    assert "low" not in linked
    assert len([news_id for news_id in linked if news_id.startswith("tc")]) == 2
    assert events.last_media_stats.candidates == 5
    assert events.last_media_stats.selected == 2

    # Curation only skips the link. Every article is still stored, including the
    # ones the digest did not link, so search and a later refresh still see them.
    assert store.get_news("low") is not None
    assert store.get_news("tc3") is not None


def test_persist_media_settings_are_injectable() -> None:
    events = DigestStore()
    items = [article(f"m{index}", source=f"Outlet {index}", importance=90) for index in range(1, 6)]

    events.persist(
        date=DIGEST_DATE,
        window=window(),
        news_items=items,
        github_projects=[],
        media_settings=MediaSelectionSettings(max_total=1, max_per_source=1),
    )

    assert len(store.get_digest(DIGEST_DATE).news) == 1
    assert events.last_media_stats.selected == 1


def test_the_digest_summary_describes_what_it_actually_links() -> None:
    """Curation must not leave a source named in the summary but absent from it."""
    events = DigestStore()
    items = [
        article("official", source="OpenAI", source_type="official"),
        article("low", source="Ars Technica", importance=10),
    ]

    events.persist(date=DIGEST_DATE, window=window(), news_items=items, github_projects=[])

    digest = store.get_digest(DIGEST_DATE)
    assert "Ars Technica" not in digest.description
    assert "OpenAI" in digest.description
    assert f"{len(digest.news)} 条更新" in digest.description


def test_persist_logs_a_quiet_summary_and_keeps_detail_behind_a_flag(caplog, monkeypatch) -> None:
    monkeypatch.delenv("AI_DAILY_DEBUG_MEDIA_SELECTION", raising=False)
    events = DigestStore()
    items = [
        article("official", source="OpenAI", source_type="official"),
        article("media", source="TechCrunch AI", importance=90),
        article("low", source="Ars Technica", importance=10),
    ]

    with caplog.at_level("INFO", logger="app.services.media_selection"):
        events.persist(date=DIGEST_DATE, window=window(), news_items=items, github_projects=[])
    assert "media selection: candidates=2" in caplog.text
    assert "KEEP" not in caplog.text

    caplog.clear()
    monkeypatch.setenv("AI_DAILY_DEBUG_MEDIA_SELECTION", "1")
    with caplog.at_level("INFO", logger="app.services.media_selection"):
        events.persist(date=DIGEST_DATE, window=window(), news_items=items, github_projects=[])
    assert "KEEP TechCrunch AI" in caplog.text
    assert "reason=importance<60" in caplog.text


def test_no_media_means_no_log_line(caplog) -> None:
    events = DigestStore()
    items = [article("official", source="OpenAI", source_type="official")]

    with caplog.at_level("INFO", logger="app.services.media_selection"):
        events.persist(date=DIGEST_DATE, window=window(), news_items=items, github_projects=[])

    assert caplog.text == ""


# --- settings ---


def test_every_rule_lives_in_settings() -> None:
    settings = MediaSelectionSettings()

    assert settings.min_importance == 60
    assert settings.max_total == 5
    assert settings.max_per_source == 2
    assert DEFAULT_SETTINGS == settings


def test_settings_are_frozen() -> None:
    with pytest.raises(Exception):
        MediaSelectionSettings().max_total = 99  # type: ignore[misc]
