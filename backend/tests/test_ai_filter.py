"""Phase 10.11: deciding whether a story from a wide feed is about AI.

Ars Technica's AI category still carries gadget, business and security stories
that only brush against the subject. Those have to be dropped before dedupe,
ranking and the LLM, and the rule has to be traceable to a word rather than to a
model's opinion.
"""

from __future__ import annotations

import pytest

from app.pipelines.ai_filter import is_ai_related, match_terms


@pytest.mark.parametrize(
    "title, summary",
    [
        ("OpenAI launches a new model", ""),
        ("Anthropic publishes research on interpretability", ""),
        ("Google's Gemini 3.8 Flash ships", ""),
        ("A new open-weight LLM from Mistral", ""),
        ("Nvidia buys Hugging Face, the GitHub of AI, for $13 billion", ""),
        ("Inside the megakernel serving engine", "Faster LLM inference on H100 devices."),
        ("Machine learning for weather forecasting", ""),
        ("Claude users found ways around safeguards", "Complicating AI safeguards."),
        ("A new chatbot from a small startup", ""),
    ],
)
def test_strong_evidence_keeps_a_story(title: str, summary: str) -> None:
    assert is_ai_related(title, summary) is True


@pytest.mark.parametrize(
    "title, summary",
    [
        # A plain mention of AI is not evidence: these are the stories that used
        # to slip through on the substring "AI".
        ("Why this month's Microsoft patch release is a doozy", "Patches ahead of AI-assisted attacks."),
        ("Panic builds over a bankrupt airline's data sale", "Bankruptcy cannot become the land grab for AI."),
        ("Google's genome system evaluates every one-base change", "Few changes matter."),
        ("The best laptop deals this week", "Save on a new machine."),
        ("Once popular for attacking AI, ASCII smuggling spreads", "A block of unicode gains use."),
    ],
)
def test_a_passing_mention_is_not_enough(title: str, summary: str) -> None:
    assert is_ai_related(title, summary) is False


def test_one_signal_family_counts_once() -> None:
    """``robot`` and ``robotics`` are one idea, not two pieces of evidence.

    A robot-dog review uses that vocabulary throughout; counting the two
    spellings separately would let it into an AI digest on a technicality.
    """
    assert is_ai_related("I spent $4,000 on a robot dog from China", "Unitree might be the most important robotics company.") is False
    assert is_ai_related("The rise of robotics", "") is False


def test_two_separate_families_are_enough() -> None:
    assert is_ai_related("Update to the AI weather model improves forecasts", "") is True
    assert is_ai_related("A benchmark for inference chips", "") is True


def test_ai_plus_one_other_signal_is_enough() -> None:
    assert is_ai_related("AI regulation moves forward", "") is True
    assert is_ai_related("The AI data centre build-out", "") is True


def test_match_terms_reports_what_it_found() -> None:
    strong, weak = match_terms("OpenAI ships a new agent framework for Gemini users")
    assert "openai" in strong
    assert "gemini" in strong
    assert "agent" in weak
    assert "ai" not in weak


def test_match_terms_is_case_insensitive_and_whole_word() -> None:
    strong, weak = match_terms("OPENAI and LLM work")
    assert strong == ["llm", "openai"]
    # "ai" must not fire inside "said" or "email".
    assert match_terms("He said the email arrived")[1] == []


def test_match_terms_handles_empty_input() -> None:
    assert match_terms("") == ([], [])
    assert is_ai_related("", "") is False