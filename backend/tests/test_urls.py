from app.pipelines.urls import canonicalize_url


def test_canonicalize_strips_fragment_and_tracking() -> None:
    url = "https://HuggingFace.co/blog/eval-datasets/?utm_source=rss&utm_medium=feed#intro"
    assert canonicalize_url(url) == "https://huggingface.co/blog/eval-datasets"


def test_canonicalize_keeps_non_tracking_query() -> None:
    url = "https://example.com/path?lang=en&utm_campaign=x"
    assert canonicalize_url(url) == "https://example.com/path?lang=en"


def test_canonicalize_trailing_slash() -> None:
    assert canonicalize_url("https://deepmind.google/blog/scaling-world-models/") == "https://deepmind.google/blog/scaling-world-models"
    assert canonicalize_url("https://deepmind.google/") == "https://deepmind.google/"
