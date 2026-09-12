from __future__ import annotations

# Deterministic AI/dev-AI keywords. Keep them here, not scattered in collectors.
AI_KEYWORDS: tuple[str, ...] = (
    "ai",
    "artificial intelligence",
    "llm",
    "large language model",
    "agent",
    "agentic",
    "rag",
    "transformer",
    "diffusion",
    "machine learning",
    "deep learning",
    "vision",
    "multimodal",
    "inference",
    "embedding",
    "chatbot",
    "copilot",
    "mcp",
    "model",
)

TRENDING_URL = "https://github.com/trending?since=daily"
GITHUB_API_BASE = "https://api.github.com"
MAX_PROJECTS = 10
MIN_AI_SCORE = 2
TOPIC_HIT_SCORE = 3
DESCRIPTION_HIT_SCORE = 2
NAME_HIT_SCORE = 1
