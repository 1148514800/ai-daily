"""Phase 10.13: the five first-party Chinese sources, exercised from fixtures.

Every extractor is pinned to a captured payload rather than to the live page, so
the suite stays offline. The property each one has to hold is the same across
all five: a real listing yields dated articles, an empty listing yields nothing
without reporting a change, and markup that no longer carries the listing is
reported as a structure change instead of as an empty day.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.collectors.html import (
    PageStructureError,
    bytedance_seed_entries,
    collect_html_source,
    minimax_entries,
    parse_html_page,
    tencent_hunyuan_entries,
    zhipu_entries,
)
from app.collectors.rss import parse_feed
from app.config.sources import source_by_id, enabled_sources
from app.config.timezone import app_timezone
from tests.conftest import EMPTY_HTML, read_fixture

UTC = timezone.utc

SEED_BLOG = read_fixture("seed_blog.html")
HUNYUAN_JSON = read_fixture("hunyuan_blog.json")
ZHIPU_NEWS = read_fixture("zhipu_news.html")
MINIMAX_BLOG = read_fixture("minimax_blog.html")
ERNIE_XML = read_fixture("ernie_blog.xml")

NEW_SOURCE_IDS = (
    "bytedance-seed",
    "tencent-hunyuan",
    "baidu-ernie",
    "zhipu-glm",
    "minimax",
)


# --- configuration ---


def test_new_sources_are_enabled_and_official() -> None:
    found = {source.id: source for source in enabled_sources()}
    for source_id in NEW_SOURCE_IDS:
        assert source_id in found, source_id
        assert found[source_id].source_type == "official", source_id
        assert found[source_id].url.startswith("https://"), source_id
        assert found[source_id].name, source_id


def test_official_priority_band_still_ends_before_research() -> None:
    """The five new sources join the official band without crossing into it."""
    priorities = {source.id: source.priority for source in enabled_sources()}
    official = [p for sid, p in priorities.items() if source_by_id(sid).source_type == "official"]
    research = [p for sid, p in priorities.items() if source_by_id(sid).source_type == "research"]

    assert max(official) < min(research)
    for source_id in NEW_SOURCE_IDS:
        assert priorities[source_id] in official


def test_only_the_hugo_feed_declares_a_resolution_base() -> None:
    """``base_url`` exists for site-relative links, not as a second address."""
    assert source_by_id("baidu-ernie").base_url == "https://ernie.baidu.com"
    for source in enabled_sources():
        if source.id != "baidu-ernie":
            assert source.base_url == "", source.id


# --- ByteDance Seed ---


def test_seed_payload_parses_title_date_and_slug() -> None:
    entries = bytedance_seed_entries(SEED_BLOG)

    # The slug is the Chinese TitleKey, so the article URL carries CJK rather
    # than the English title's transliteration.
    assert entries[0][0] == (
        "https://seed.bytedance.com/blog/"
        "seedrealtime-音视频全双工大模型发布-走向全模态自然交互"
    )
    assert entries[0][1] == "SeedRealtime 音视频全双工大模型发布：走向全模态自然交互"
    assert all(url.startswith("https://seed.bytedance.com/blog/") for url, _t, _p in entries)
    # PublishDate is epoch milliseconds naming the local calendar day's midnight,
    # so the stored instant is that moment in UTC (2026-08-05 00:00 Shanghai).
    assert entries[0][2] == datetime(2026, 8, 4, 16, 0, tzinfo=UTC)
    assert entries[0][2].astimezone(app_timezone()).date().isoformat() == "2026-08-05"


def test_seed_skips_a_record_without_a_publish_date() -> None:
    entries = bytedance_seed_entries(SEED_BLOG)

    assert all(title != "无日期草稿" for _url, title, _published in entries)


def test_seed_empty_list_is_not_a_structure_change() -> None:
    result = parse_html_page(source_by_id("bytedance-seed"), index_html=EMPTY_HTML["bytedance-seed"])

    assert result.success is True
    assert result.valid == []


def test_seed_missing_payload_is_a_structure_change() -> None:
    with pytest.raises(PageStructureError):
        bytedance_seed_entries("<html><body><p>We redesigned the blog.</p></body></html>")


def test_seed_unreadable_payload_is_a_structure_change() -> None:
    with pytest.raises(PageStructureError):
        bytedance_seed_entries("<html><script>window._ROUTER_DATA = {not json}</script></html>")


def test_seed_duplicate_links_are_deduped() -> None:
    """One post listed twice collapses to one article, and says so."""
    payload = SEED_BLOG[SEED_BLOG.index("window._ROUTER_DATA = ") + len("window._ROUTER_DATA = ") :]
    payload = payload[: payload.index("</script>")]
    data = json.loads(payload)
    records = data["loaderData"]["(locale$)/blog/page"]["article_list"]
    data["loaderData"]["(locale$)/blog/page"]["article_list"] = records + records
    doubled = "<html><body><script>window._ROUTER_DATA = " + json.dumps(data, ensure_ascii=False) + "</script></body></html>"
    result = parse_html_page(source_by_id("bytedance-seed"), index_html=doubled)

    assert result.success is True
    ids = [article.canonical_url for article in result.valid]
    assert len(ids) == len(set(ids))
    # Eight records in, six dated (the undated pair is dropped by the extractor),
    # so three of the six are duplicates of an article already seen.
    assert len(records) * 2 == 8
    assert len(result.valid) == 3
    assert result.skipped == 3


# --- 腾讯混元 ---


def test_hunyuan_listing_parses_titles_and_epoch_seconds() -> None:
    entries = tencent_hunyuan_entries(HUNYUAN_JSON)

    assert entries[0] == (
        "https://hunyuan.tencent.com/research/hy4-preview",
        "Hy4 preview 发布",
        datetime(2026, 8, 27, 16, 0, tzinfo=UTC),
    )
    assert all(url.startswith("https://hunyuan.tencent.com/research/") for url, _t, _p in entries)


def test_hunyuan_error_payload_is_a_structure_change() -> None:
    with pytest.raises(PageStructureError):
        tencent_hunyuan_entries('{"code": 500, "msg": "server error"}')


def test_hunyuan_missing_list_is_a_structure_change() -> None:
    with pytest.raises(PageStructureError):
        tencent_hunyuan_entries('{"code": 0, "data": {"totalNum": 9}}')


def test_hunyuan_empty_list_is_not_a_structure_change() -> None:
    result = parse_html_page(source_by_id("tencent-hunyuan"), index_html=EMPTY_HTML["tencent-hunyuan"])

    assert result.success is True
    assert result.valid == []


def test_hunyuan_record_without_a_slug_or_date_is_skipped() -> None:
    payload = (
        '{"code":0,"data":{"list":['
        '{"id":1,"title":"No date"},'
        '{"title":"No slug","displayPublishTime":1787846400},'
        '{"id":3,"title":"Complete","customUrl":"ok","displayPublishTime":1787846400}'
        "]}}"
    )
    entries = tencent_hunyuan_entries(payload)

    assert [title for _u, title, _p in entries] == ["Complete"]


# --- 百度文心 ---


def test_ernie_feed_is_a_real_rss_feed() -> None:
    source = source_by_id("baidu-ernie")
    result = parse_feed(ERNIE_XML, source)

    assert result.success is True
    assert len(result.valid) == 3
    assert result.valid[0].source_type == "official"
    assert result.valid[0].source == "百度文心"


def test_ernie_site_relative_links_resolve_against_the_site() -> None:
    """Hugo writes ``/blog/posts/x``; storing that verbatim would be unusable."""
    result = parse_feed(ERNIE_XML, source_by_id("baidu-ernie"))

    assert result.valid[0].url == "https://ernie.baidu.com/blog/posts/ernie-5.1-0508-release/"
    assert all(article.canonical_url.startswith("https://ernie.baidu.com/") for article in result.valid)


def test_ernie_relative_link_is_dropped_without_a_base_url() -> None:
    """Guessing an origin would be worse than skipping the entry."""
    source = source_by_id("baidu-ernie").__class__(
        id="baidu-ernie",
        name="百度文心",
        url="https://ernie.baidu.com/index.xml",
        source_type="official",
    )
    result = parse_feed(ERNIE_XML, source)

    assert result.valid == []
    assert result.skipped == 3


def test_ernie_entries_carry_their_publish_dates() -> None:
    result = parse_feed(ERNIE_XML, source_by_id("baidu-ernie"))
    published = [article.published_at for article in result.valid]

    assert published[0] == datetime(2026, 5, 9, tzinfo=UTC)
    assert published == sorted(published, reverse=True)


# --- 智谱 GLM ---


def test_zhipu_flight_payload_parses_both_categories() -> None:
    entries = zhipu_entries(ZHIPU_NEWS)

    by_url = {url: title for url, title, _p in entries}
    assert by_url["https://www.zhipuai.cn/zh/news/152"] == "智谱首份业绩报告发布，探索AGI智能上界"
    # A ``blog`` record is a research post, and its URL segment says so.
    assert "https://www.zhipuai.cn/zh/research/9001" in by_url


def test_zhipu_missing_payload_is_a_structure_change() -> None:
    with pytest.raises(PageStructureError):
        zhipu_entries("<html><body>nothing here</body></html>")


def test_zhipu_unterminated_array_is_a_structure_change() -> None:
    with pytest.raises(PageStructureError):
        zhipu_entries('<script>self.__next_f.push([1,"\\"newsItems\\":[{\\"id\\":1}")</script>')


def test_zhipu_empty_list_is_not_a_structure_change() -> None:
    result = parse_html_page(source_by_id("zhipu-glm"), index_html=EMPTY_HTML["zhipu-glm"])

    assert result.success is True
    assert result.valid == []


def test_zhipu_record_without_a_date_is_skipped() -> None:
    entries = zhipu_entries(ZHIPU_NEWS)

    assert all(title != "无日期记录" for _u, title, _p in entries)


def test_zhipu_timestamps_are_utc() -> None:
    entries = zhipu_entries(ZHIPU_NEWS)
    published = [moment for _u, _t, moment in entries]

    assert all(moment.tzinfo is not None for moment in published)
    assert entries[0][2] == datetime(2026, 3, 31, 10, 0, tzinfo=UTC)


# --- MiniMax ---


def test_minimax_cards_parse_headline_and_date() -> None:
    entries = minimax_entries(MINIMAX_BLOG)

    assert entries[0] == (
        "https://www.minimax.cn/blog/minimax-music-3-0-cn",
        "MiniMax Music 3.0：新一代开放权重、生产级全能音乐模型",
        datetime(2026, 8, 13, tzinfo=UTC),
    )


def test_minimax_skips_an_undated_card() -> None:
    entries = minimax_entries(MINIMAX_BLOG)

    assert all(title != "一条没有日期的笔记" for _u, title, _p in entries)


def test_minimax_duplicate_links_are_deduped() -> None:
    entries = minimax_entries(MINIMAX_BLOG)
    urls = [url for url, _t, _p in entries]

    assert len(urls) == len(set(urls)) == 3


def test_minimax_page_without_listing_links_is_a_structure_change() -> None:
    with pytest.raises(PageStructureError):
        minimax_entries("<html><body><p>Blog moved.</p></body></html>")


def test_minimax_empty_listing_is_not_a_structure_change() -> None:
    result = parse_html_page(source_by_id("minimax"), index_html=EMPTY_HTML["minimax"])

    assert result.success is True
    assert result.valid == []


# --- end to end through each collector ---


@pytest.mark.parametrize(
    "source_id, payload, expected",
    [
        ("bytedance-seed", SEED_BLOG, 3),
        ("tencent-hunyuan", HUNYUAN_JSON, 3),
        ("zhipu-glm", ZHIPU_NEWS, 3),
        ("minimax", MINIMAX_BLOG, 3),
    ],
)
def test_collect_html_source_returns_the_listing(source_id: str, payload: str, expected: int) -> None:
    """The whole collector, not just the entry parser, for each new source."""
    source = source_by_id(source_id)
    result = collect_html_source(
        source, fetch_text=lambda url, timeout=10.0: payload
    )

    assert result.success is True, result.error
    assert len(result.valid) == expected
    assert all(article.source_id == source_id for article in result.valid)
    assert all(article.published_at is not None for article in result.valid)


def test_hunyuan_uses_its_own_post_fetcher() -> None:
    """Its listing endpoint is POST-only, so it must not read through fetch_html."""
    calls: list[str] = []

    def listing(url: str, timeout: float = 10.0) -> str:
        calls.append(url)
        return HUNYUAN_JSON

    def wrong_fetcher(url: str, timeout: float = 10.0) -> str:
        raise AssertionError("the page fetcher must not be used for Hunyuan")

    result = collect_html_source(
        source_by_id("tencent-hunyuan"), fetch_listing=listing, fetch_text=wrong_fetcher
    )

    assert result.success is True
    assert len(result.valid) == 3
    assert calls == ["https://api.hunyuan.tencent.com/api/blog/publicList"]


def test_a_changed_page_fails_only_its_own_source() -> None:
    """A structure change is reported, and stays inside the one source."""
    result = collect_html_source(
        source_by_id("minimax"), fetch_text=lambda url, timeout=10.0: "<html><body>gone</body></html>"
    )

    assert result.success is False
    assert result.error
