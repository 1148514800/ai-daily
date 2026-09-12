from __future__ import annotations

# Deterministic GitHub AI relevance keywords.
# Keep them here, not scattered in collectors.

# Core AI evidence: unambiguous, stands on its own.
CORE_AI_KEYWORDS: tuple[str, ...] = (
    "llm",
    "large language model",
    "generative ai",
    "machine learning",
    "deep learning",
    "artificial intelligence",
    "transformer",
    "diffusion",
    "rag",
    "retrieval augmented generation",
    "multimodal",
    "computer vision",
    "stable diffusion",
    "pytorch",
    "tensorflow",
    "huggingface",
    "langchain",
)

# Strong AI tooling. Real projects usually tag these in topics *and* mention
# them in the description, so a lone mention is not enough by itself.
TOOLING_AI_KEYWORDS: tuple[str, ...] = (
    "mcp",
    "model context protocol",
)

STRONG_AI_KEYWORDS: tuple[str, ...] = CORE_AI_KEYWORDS + TOOLING_AI_KEYWORDS

# Ambiguous keywords that also appear in ordinary software.
# They can never decide acceptance on their own.
WEAK_AI_KEYWORDS: tuple[str, ...] = (
    "ai",
    "agent",
    "agentic",
    "model",
    "vision",
    "inference",
    "embedding",
    "chat",
    "chatbot",
    "assistant",
    "copilot",
)

# Conservative hints for obvious non-AI products.
# They only veto weak or tooling-only evidence, never core AI evidence.
NEGATIVE_HINTS: tuple[str, ...] = (
    "crm",
    "finance tracker",
    "todo",
    "game",
    "music player",
    "desktop utility",
    "adhd",
    "marketing website",
    "ecommerce store",
)

TRENDING_URL = "https://github.com/trending?since=daily"
GITHUB_API_BASE = "https://api.github.com"
MAX_PROJECTS = 10

# Strong keyword scores per field.
TOPIC_STRONG_SCORE = 4
DESCRIPTION_STRONG_SCORE = 3
NAME_STRONG_SCORE = 2
EXTRA_STRONG_SCORE = 1
MAX_EXTRA_STRONG_SCORE = 2

# Weak keyword scores.
WEAK_HIT_SCORE = 1
MAX_WEAK_SCORE = 3
# Distinct weak keywords needed before the weak route is considered.
WEAK_MIN_COUNT = 2

# Normal mode (GitHub REST metadata + topics available).
# Tooling-only evidence must clear this bar.
MIN_AI_SCORE = 6
# Strict fallback (metadata unavailable, Trending description only).
# Only core AI evidence counts, so a single core keyword is the effective bar.
STRICT_MIN_AI_SCORE = 3
