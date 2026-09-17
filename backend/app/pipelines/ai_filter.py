"""Decide whether a story from a general-interest feed is really about AI.

Most sources are already topic-restricted: OpenAI publishes AI news and nothing
else. A few feeds are broader than the section they claim to be, so an entry
reaching the pipeline can be about a security patch, a bankruptcy, or a phone
review. Those must be dropped *before* dedupe, ranking and the LLM, because a
story that is not about AI has no place in an AI digest and would cost a model
call to summarise.

The rule is deterministic and stated as evidence rather than as a vibe:

* one **strong** term is enough — these only occur in AI coverage
  (``artificial intelligence``, ``openai``, ``llm``, ``gemini``, ...);
* a bare ``AI`` is **not** enough by itself, which is exactly the case the phase
  is about: an article that mentions AI in passing must not survive on that.
  Two independent weak signals, or one weak signal next to ``AI``, are needed.
  "Independent" is counted by signal, not by spelling: ``robot`` and
  ``robotics`` in the same sentence are one piece of evidence, so a robot-dog
  review does not qualify on its own vocabulary.

No model is involved, so the same feed always yields the same subset and a
wrong keep/drop can be traced to one word in ``AI_STRONG`` / ``AI_WEAK``.
"""

from __future__ import annotations

import re

# Terms that appear in AI coverage and essentially nowhere else. Matched as
# whole words or phrases over the folded title + summary.
AI_STRONG = (
    "artificial intelligence",
    "machine learning",
    "machine-learning",
    "deep learning",
    "neural network",
    "neural networks",
    "large language model",
    "language model",
    "generative ai",
    "genai",
    "llm",
    "llms",
    "chatbot",
    "chatgpt",
    "openai",
    "anthropic",
    "deepmind",
    "hugging face",
    "huggingface",
    "deepseek",
    "mistral",
    "cohere",
    "perplexity",
    "midjourney",
    "stable diffusion",
    "copilot",
    "gemini",
    "claude",
    "llama",
    "grok",
    "qwen",
    "kimi",
    "ai model",
    "ai models",
    "ai agent",
    "ai agents",
    "ai chatbot",
    "ai assistant",
    "ai assistants",
    "ai safety",
    "ai regulation",
    "ai policy",
    "ai system",
    "ai systems",
    "ai startup",
    "ai company",
    "ai firms",
    "ai research",
    "ai training",
    "ai-generated",
    "ai generated",
    "ai chip",
    "ai chips",
    "ai data center",
    "ai data centre",
    "ai infrastructure",
    "ai vibe",
    "prompt injection",
    "fine-tune",
    "fine-tuning",
    "diffusion model",
    "transformer model",
    # --- Chinese AI brands (Phase 10.13) ---
    #
    # Each of these names a model or product rather than a company, which is the
    # line that matters here: 百度, 腾讯 and 字节 publish plenty of news that has
    # nothing to do with AI, so those company names are deliberately absent from
    # both lists and can never admit a story on their own.
    "doubao",
    "豆包",
    "bytedance seed",
    "seedance",
    "seedream",
    "hunyuan",
    "腾讯混元",
    "混元",
    "ernie",
    "文心",
    "文心大模型",
    "文心一言",
    "glm",
    "chatglm",
    "智谱",
    "zhipu",
    "autoglm",
    "minimax",
    "hailuo",
    "海螺",
)

# Terms that suggest AI but also occur outside it. They only count together with
# another signal, so "research"/"policy"/"chip" alone never admits a story.
AI_WEAK = (
    "ai",
    "a.i.",
    "agent",
    "agents",
    "agentic",
    "robot",
    "robots",
    "robotics",
    "automation",
    "algorithm",
    "algorithmic",
    "dataset",
    "data center",
    "data centre",
    "gpu",
    "chips",
    "semiconductor",
    "inference",
    "benchmark",
    "benchmarks",
    "alignment",
    "model",
    "models",
    "compute",
    "policy",
    "regulation",
    "research",
    "prompt",
    "cloud",
)

# Weak terms that express the *same* idea. Two spellings of one signal are one
# piece of evidence, not two: an article about a robot dog mentions "robot" and
# "robotics" throughout and would otherwise look like it had two independent
# reasons to be in an AI digest. Terms absent from this map are their own family.
WEAK_FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ai", ("ai", "a.i.")),
    ("agent", ("agent", "agents", "agentic")),
    ("robot", ("robot", "robots", "robotics")),
    ("algorithm", ("algorithm", "algorithmic")),
    ("benchmark", ("benchmark", "benchmarks")),
    ("model", ("model", "models")),
    ("chip", ("chips", "semiconductor")),
    ("datacenter", ("data center", "data centre")),
    ("automation", ("automation",)),
)

WEAK_FAMILY_OF: dict[str, str] = {
    term: family for family, terms in WEAK_FAMILIES for term in terms
}


def _pattern(term: str) -> re.Pattern[str]:
    """Whole-word/phrase matcher; terms are literal, so they are escaped.

    The boundaries stop a term matching inside a longer *word* (``glm`` must not
    fire inside ``glimmer``), but a trailing digit is allowed through, because
    that is how models are versioned: ``Hunyuan3D``, ``混元3D``, ``GLM4`` and
    ``Gemini2.5`` are the same signal as the plain name. The leading boundary
    stays strict, so ``said`` and ``email`` still cannot produce ``ai``.
    """
    return re.compile(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z])")


STRONG_PATTERNS = tuple((term, _pattern(term)) for term in AI_STRONG)
WEAK_PATTERNS = tuple((term, _pattern(term)) for term in AI_WEAK)


def _fold(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def match_terms(text: str) -> tuple[list[str], list[str]]:
    """``(strong terms, weak terms)`` found in ``text``, each without repeats."""
    folded = _fold(text)
    if not folded:
        return [], []
    strong = [term for term, pattern in STRONG_PATTERNS if pattern.search(folded)]
    weak = [term for term, pattern in WEAK_PATTERNS if pattern.search(folded)]
    return strong, weak


def is_ai_related(title: str, summary: str = "") -> bool:
    """Whether a story carries enough evidence to belong in an AI digest.

    One strong term anywhere is decisive. Otherwise the story needs a weak term
    beyond a bare ``AI``: either the word ``AI`` plus one other weak term, or two
    weak terms from *different* signal families. That is what keeps a passing
    mention of AI in a security or business story out of the digest, and what
    stops a review that says "robot" and "robotics" from qualifying twice on one
    idea.
    """
    strong, weak = match_terms(f"{title} \n {summary}")
    if strong:
        return True
    others = [term for term in weak if WEAK_FAMILY_OF.get(term, term) != "ai"]
    if not others:
        return False
    mentions_ai = len(weak) > len(others)
    families = {WEAK_FAMILY_OF.get(term, term) for term in others}
    return mentions_ai or len(families) >= 2
