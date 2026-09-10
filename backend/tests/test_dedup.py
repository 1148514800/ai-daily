from datetime import datetime, timezone

from app.collectors.raw import RawArticle
from app.pipelines.dedup import dedupe_articles, normalize_title
from app.pipelines.urls import canonicalize_url


def article(**kwargs) -> RawArticle:
    url = kwargs.get("url", "https://example.com/a")
    defaults = dict(
        source_id="openai",
        source="OpenAI",
        source_type="official",
        title="Hello World",
        url=url,
        canonical_url=canonicalize_url(url),
        published_at=datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc),
        summary="",
    )
    defaults.update(kwargs)
    defaults["canonical_url"] = canonicalize_url(defaults["url"])
    return RawArticle(**defaults)


def test_url_duplicates_are_removed() -> None:
    first = article(url="https://huggingface.co/blog/eval-datasets?utm_source=rss")
    second = article(
        source_id="huggingface",
        source="Hugging Face",
        source_type="blog",
        url="https://huggingface.co/blog/eval-datasets/",
    )
    result = dedupe_articles([first, second])
    assert len(result) == 1
    assert result[0].source_id == "openai"


def test_identical_titles_within_48h_are_duplicates() -> None:
    openai = article(title="GPT-6 Astra: The next generation in intelligence for work")
    deepmind = article(
        source_id="deepmind",
        source="Google DeepMind",
        source_type="official",
        title="GPT-6 Astra:  The next generation in intelligence for work!",
        url="https://deepmind.google/blog/gpt-6-astra-recap",
        published_at=datetime(2026, 9, 10, 13, 0, tzinfo=timezone.utc),
    )
    result = dedupe_articles([deepmind, openai])
    assert len(result) == 1
    assert result[0].source_id == "openai"


def test_different_titles_are_kept() -> None:
    first = article(title="Scaling world models", url="https://deepmind.google/blog/scaling-world-models")
    second = article(title="Cool Model Card", url="https://huggingface.co/blog/cool-model", source_id="huggingface", source="Hugging Face", source_type="blog")
    result = dedupe_articles([first, second])
    assert len(result) == 2


def test_title_normalize_is_conservative() -> None:
    assert normalize_title("Hello,  World!") == "hello world"
    assert normalize_title("Hello World") != normalize_title("Hello Worlds")


def test_dedup_is_stable() -> None:
    items = [
        article(title="Same Title", url="https://openai.com/a", source_id="openai", source_type="official"),
        article(title="Same Title", url="https://deepmind.google/a", source_id="deepmind", source="Google DeepMind", source_type="official"),
        article(title="Same Title", url="https://huggingface.co/a", source_id="huggingface", source="Hugging Face", source_type="blog"),
    ]
    first = [item.url for item in dedupe_articles(items)]
    second = [item.url for item in dedupe_articles(list(reversed(items)))]
    assert first == second
    assert first == ["https://openai.com/a"]
