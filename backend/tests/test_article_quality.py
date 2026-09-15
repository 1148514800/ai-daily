"""Phase 10.11: the deterministic verdict on an extracted body.

Cleaning removes chrome it recognises, but a page can still hand back a cookie
wall or a menu. Storing that as the article would be worse than storing the
feed's own summary, so the verdict is measured rather than guessed at.
"""

from __future__ import annotations

from app.services.article_quality import (
    FALLBACK,
    GOOD,
    LOW,
    QUALITY_VALUES,
    assess_quality,
    effective_length,
    is_noise_paragraph,
    paragraphs_of,
)

REAL_ARTICLE = (
    "Cohere released North Small Translate today, an open-weight machine "
    "translation model aimed at regulated industries that need to keep their "
    "data inside their own infrastructure.\n\n"
    "The company says the model is available under a permissive licence and that "
    "it was trained on a curated mix of public and licensed parallel text, which "
    "it describes in a short technical note alongside the weights.\n\n"
    "Existing users can call the model through the same API endpoint and pay the "
    "same per-character rate, the company said, and the weights are published on "
    "the usual model hub for anyone who would rather self-host the model behind "
    "their own firewall instead of sending text to a hosted service."
)

MENU_PAGE = " | ".join(
    [
        "Home",
        "Blog",
        "Pricing",
        "Docs",
        "Login",
        "Sign up",
        "Careers",
        "Contact",
        "Support",
        "Status",
        "Product",
        "Company",
        "Legal",
        "Trust",
        "Security",
        "Accept all cookies",
        "Manage cookies",
        "Subscribe to our newsletter",
        "Share this article",
        "Related articles",
        "Recommended for you",
        "Read more",
        "© 2026 Example Inc. All rights reserved",
        "Privacy Policy",
        "Terms of Use",
        "Follow us on X",
        "Facebook",
        "LinkedIn",
        "Tags: ai models research",
    ]
)


def test_a_real_article_is_good() -> None:
    verdict = assess_quality(REAL_ARTICLE)
    assert verdict.verdict == GOOD
    assert verdict.usable is True
    assert verdict.paragraphs == 3


def test_a_navigation_page_is_not_good() -> None:
    """A page of labels is refused rather than stored as the article."""
    verdict = assess_quality(MENU_PAGE)
    assert verdict.verdict in {LOW, FALLBACK}
    assert verdict.usable is False
    assert verdict.reason


def test_a_menu_paragraph_list_is_not_good() -> None:
    menu = "\n\n".join(
        ["Home", "Blog", "Pricing", "Docs", "Login", "Sign up", "Careers", "Contact"] * 3
    )
    verdict = assess_quality(menu)
    assert verdict.verdict in {LOW, FALLBACK}
    assert verdict.usable is False


def test_nothing_at_all_is_fallback() -> None:
    assert assess_quality("").verdict == FALLBACK
    assert assess_quality("   \n\n  ").verdict == FALLBACK
    assert assess_quality("").reason == "empty"


def test_a_short_body_is_fallback_but_a_short_feed_summary_is_low() -> None:
    """A feed's own teaser is short by design and is labelled, not rejected."""
    short = "OpenAI 今天发布了新的推理模式。"
    assert assess_quality(short).verdict == FALLBACK
    assert assess_quality(short).reason == "too_short"
    assert assess_quality(short, method="rss_summary").verdict == LOW
    assert assess_quality(short, method="rss_summary").reason == "short_summary"


def test_a_repetitive_template_is_not_good() -> None:
    repeated = "\n\n".join(["Posted on September 10, 2026 by the Example team"] * 8)
    verdict = assess_quality(repeated)
    assert verdict.verdict in {LOW, FALLBACK}
    assert verdict.duplicate_ratio > 0.35


def test_chinese_counts_as_more_than_its_character_length() -> None:
    """A Chinese paragraph of 160 characters is a real article, not a snippet."""
    chinese = (
        "今天发布的新模型支持更长的上下文窗口，官方表示它在多步推理任务上取得了明显提升，"
        "并且已经在接口中默认开启。团队还公开了评测数据，说明新版本在长文本任务上的表现优于上一个版本，"
        "同时保持了相近的推理成本。开发者只需要把模型名称换成新的版本号，就可以在现有代码里直接使用，"
        "不需要改动任何调用参数。官方文档里还给出了一个完整的示例，演示如何在一次请求中同时处理多个文档，"
        "以及如何控制输出长度，避免因为上下文过长而导致请求被拒绝。"
    )
    assert len(chinese) < 400
    assert effective_length(chinese) >= 400
    assert assess_quality(chinese).verdict == GOOD


def test_a_cookie_sentence_is_not_noise_but_a_cookie_banner_is() -> None:
    """Noise is judged by wording and length, never by the word "cookie"."""
    assert is_noise_paragraph("Accept all cookies") is True
    assert is_noise_paragraph("Manage cookies") is True
    assert (
        is_noise_paragraph(
            "The site sets a cookie so that a reader's language choice survives a reload."
        )
        is False
    )


def test_noise_wording_that_appears_inside_prose_is_kept() -> None:
    assert is_noise_paragraph("Subscribe to our newsletter") is True
    assert (
        is_noise_paragraph(
            "Readers who subscribe to the newsletter get the research notes a day early."
        )
        is False
    )
    assert is_noise_paragraph("Share this article") is True
    assert (
        is_noise_paragraph("The team decided to share the article's data under an open licence.")
        is False
    )


def test_paragraphs_of_splits_on_blank_lines() -> None:
    assert paragraphs_of("one\n\ntwo\n\n\nthree") == ["one", "two", "three"]
    assert paragraphs_of("") == []


def test_the_three_verdicts_are_the_documented_values() -> None:
    assert set(QUALITY_VALUES) == {"good", "low", "fallback"}
