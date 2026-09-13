"""Deterministic topic and company detection for digest ranking.

Ranking needs two coarse labels per story: what it is about (``topic``) and who
it is about (``company``). Both drive the diversity reranking in
``app.services.news_ranker`` and nothing else, so they are deliberately simple.

There is no embedding model, no NER model and no LLM call here. An article is
labelled by matching keywords against its own text, which makes the label
reproducible and cheap: the same article always gets the same topic, and a
wrong label can be traced to one keyword instead of a model's opaque output.

Rules are evaluated in a fixed order and the first match wins, so the list is
ordered from the most specific topic to the least. A story that matches nothing
is ``other``; being wrong here costs only a slightly less varied digest, never a
lost article, so the classifier is allowed to stay blunt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Topic taxonomy. Kept short on purpose: a finer taxonomy would need a model,
# and the only consumer is a soft diversity penalty.
TOPIC_MODEL_RELEASE = "model_release"
TOPIC_AGENT = "agent"
TOPIC_RESEARCH = "research"
TOPIC_OPEN_SOURCE = "open_source"
TOPIC_PRODUCT = "product"
TOPIC_DEVELOPER_TOOLS = "developer_tools"
TOPIC_HARDWARE = "hardware"
TOPIC_BUSINESS = "business"
TOPIC_POLICY = "policy"
TOPIC_OTHER = "other"

TOPICS = (
    TOPIC_MODEL_RELEASE,
    TOPIC_AGENT,
    TOPIC_RESEARCH,
    TOPIC_OPEN_SOURCE,
    TOPIC_PRODUCT,
    TOPIC_DEVELOPER_TOOLS,
    TOPIC_HARDWARE,
    TOPIC_BUSINESS,
    TOPIC_POLICY,
    TOPIC_OTHER,
)


@dataclass(frozen=True)
class TopicRule:
    """One topic and the keywords that select it."""

    name: str
    keywords: tuple[str, ...]


# Order matters: the first matching rule wins. Regulation and hardware come
# before business so "chip export ban" is policy, not a market story, and
# "NVIDIA launches a chip" is hardware, not a model release.
TOPIC_RULES: tuple[TopicRule, ...] = (
    TopicRule(
        TOPIC_POLICY,
        (
            "regulation", "regulator", "regulators", "regulatory", "policy",
            "law", "laws", "lawsuit", "court", "antitrust", "compliance",
            "export control", "export controls", "copyright", "privacy",
            "ban", "bans", "banned", "investigation", "committee",
            "监管", "法案", "政策", "合规", "诉讼", "版权", "隐私",
            "反垄断", "出口管制", "禁令", "立法", "条例",
        ),
    ),
    TopicRule(
        TOPIC_HARDWARE,
        (
            "chip", "chips", "gpu", "gpus", "accelerator", "semiconductor",
            "wafer", "tpu", "supercomputer", "data center", "datacenter",
            "inference server", "h100", "h200", "b200", "gb200", "blackwell",
            "rubin", "cuda", "芯片", "显卡", "半导体", "算力", "数据中心",
            "晶圆", "超算",
        ),
    ),
    TopicRule(
        TOPIC_BUSINESS,
        (
            "funding", "raises", "raised", "raise", "valuation", "valued",
            "acquisition", "acquires", "acquired", "acquire", "merger",
            "revenue", "earnings", "ipo", "investor", "investors", "stake",
            "partnership", "partners", "pricing", "price", "prices",
            "subscription", "layoff", "layoffs", "hiring", "market share",
            "融资", "估值", "收购", "并购", "营收", "财报", "上市",
            "合作", "定价", "价格", "订阅", "裁员",
        ),
    ),
    TopicRule(
        TOPIC_RESEARCH,
        (
            "paper", "papers", "research", "researchers", "study", "studies",
            "benchmark", "benchmarks", "evaluation", "arxiv", "experiment",
            "experiments", "pretraining", "training run", "scaling law",
            "interpretability", "alignment", "reasoning", "theorem",
            "论文", "研究", "基准", "评测", "训练", "推理", "实验",
            "可解释性", "对齐",
        ),
    ),
    TopicRule(
        TOPIC_AGENT,
        (
            "agent", "agents", "agentic", "autonomous", "tool use",
            "tool calling", "computer use", "multi-agent", "orchestration",
            "智能体", "自主体", "多智能体", "工具调用",
        ),
    ),
    TopicRule(
        TOPIC_DEVELOPER_TOOLS,
        (
            "api", "sdk", "sdks", "cli", "ide", "copilot", "code completion",
            "developer", "developers", "framework", "library", "libraries",
            "openapi", "playground", "console", "debugging", "refactor",
            "开发者", "开发工具", "编程", "代码", "工具链", "函数调用",
        ),
    ),
    TopicRule(
        TOPIC_OPEN_SOURCE,
        (
            "open source", "open-source", "opensource", "open weights",
            "apache 2.0", "mit license", "hugging face", "github",
            "checkpoint", "checkpoints",
            "开源", "权重开放", "开放权重",
        ),
    ),
    TopicRule(
        TOPIC_MODEL_RELEASE,
        (
            "launches", "launch", "launched", "releases", "release", "released",
            "introducing", "introduces", "unveils", "announces", "announced",
            "general availability", "preview", "new model", "frontier model",
            "gpt", "claude", "gemini", "llama", "qwen", "deepseek", "kimi",
            "grok", "mistral", "model card",
            "发布", "推出", "上线", "开源模型", "新模型", "版本",
        ),
    ),
    TopicRule(
        TOPIC_PRODUCT,
        (
            "feature", "features", "app", "apps", "rollout", "rolling out",
            "update", "updates", "updated", "redesign", "interface",
            "subscription plan", "now available", "generally available",
            "产品", "功能", "更新", "应用", "改版", "上线",
        ),
    ),
)


@dataclass(frozen=True)
class CompanyRule:
    """One company and the keywords that identify it."""

    name: str
    keywords: tuple[str, ...]


# Order matters: the first matching company wins, so the list runs from the
# companies that own the most distinctive vocabulary to the most generic. A
# story naming two companies keeps only the first, which is a documented limit.
COMPANY_RULES: tuple[CompanyRule, ...] = (
    CompanyRule("OpenAI", ("openai", "chatgpt", "sora", "gpt")),
    CompanyRule("Anthropic", ("anthropic", "claude")),
    CompanyRule("Google DeepMind", ("deepmind", "gemini", "gemma", "google", "veo", "谷歌")),
    CompanyRule("Meta", ("meta", "llama")),
    CompanyRule("NVIDIA", ("nvidia", "cuda", "geforce", "omniverse", "英伟达")),
    CompanyRule("DeepSeek", ("deepseek", "深度求索")),
    CompanyRule("Alibaba Qwen", ("qwen", "alibaba", "tongyi", "阿里", "通义")),
    CompanyRule("Moonshot Kimi", ("kimi", "moonshot")),
    CompanyRule("Hugging Face", ("hugging face", "huggingface")),
    CompanyRule("Microsoft", ("microsoft", "copilot", "azure", "微软")),
    CompanyRule("Mistral", ("mistral",)),
    CompanyRule("xAI", ("xai", "grok")),
    CompanyRule("ByteDance", ("bytedance", "doubao", "豆包", "字节")),
)


def _is_cjk(keyword: str) -> bool:
    return any(ord(char) > 0x2E00 for char in keyword)


def _latin_pattern(keyword: str) -> re.Pattern[str]:
    """Match a latin keyword as a whole word.

    Without the boundaries "meta" would fire on "metadata" and "api" on
    "capital", which is exactly the kind of quiet mislabel that makes a
    keyword classifier untrustworthy.
    """
    return re.compile(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])")


def _compile(keywords: tuple[str, ...]) -> tuple[tuple[re.Pattern[str], ...], tuple[str, ...]]:
    latin = tuple(_latin_pattern(word) for word in keywords if not _is_cjk(word))
    cjk = tuple(word for word in keywords if _is_cjk(word))
    return latin, cjk


_TOPIC_PATTERNS = tuple((rule.name, *_compile(rule.keywords)) for rule in TOPIC_RULES)
_COMPANY_PATTERNS = tuple((rule.name, *_compile(rule.keywords)) for rule in COMPANY_RULES)


def _matches(text: str, patterns, cjk_keywords) -> bool:
    if any(pattern.search(text) for pattern in patterns):
        return True
    return any(keyword in text for keyword in cjk_keywords)


def classify_text(*texts: str | None) -> str:
    """Join the fields a label may be derived from into one lowercase string."""
    return " ".join(str(text) for text in texts if text).lower()


def detect_topic(*texts: str | None) -> str:
    """Return the first matching topic, or ``other``."""
    haystack = classify_text(*texts)
    for name, patterns, cjk_keywords in _TOPIC_PATTERNS:
        if _matches(haystack, patterns, cjk_keywords):
            return name
    return TOPIC_OTHER


def detect_company(*texts: str | None) -> str:
    """Return the first matching company, or an empty string."""
    haystack = classify_text(*texts)
    for name, patterns, cjk_keywords in _COMPANY_PATTERNS:
        if _matches(haystack, patterns, cjk_keywords):
            return name
    return ""


def topic_for_news(
    *,
    title_cn: str = "",
    title_original: str = "",
    summary: str = "",
    why_it_matters: str = "",
    source: str = "",
) -> str:
    """The topic of one news article, derived from the fields that describe it.

    This is the single definition of which article fields feed the classifier.
    The ranker and the API both go through here, so a stored article and a
    freshly collected one can never be labelled by different rules.
    """
    return detect_topic(title_cn, title_original, summary, why_it_matters, source)


def company_for_news(
    *,
    title_cn: str = "",
    title_original: str = "",
    summary: str = "",
    why_it_matters: str = "",
    source: str = "",
) -> str:
    """The company one news article is about, or an empty string.

    Same field set as ``topic_for_news``, kept next to it so the two labels are
    always derived from the same article text.
    """
    return detect_company(title_cn, title_original, summary, why_it_matters, source)


def article_text_fields(item) -> dict[str, str]:
    """The article fields a label may be derived from.

    One definition, so the ranker and the API can never disagree about which
    text counts as evidence.
    """
    return dict(
        title_cn=item.title_cn,
        title_original=item.title_original,
        summary=item.summary,
        why_it_matters=item.why_it_matters,
        source=item.source,
    )


def label_article(item) -> tuple[str, str]:
    """The ``(topic, company)`` labels for one article.

    The single entry point both the ranking and the API use, so the topic a card
    shows is always the topic the ordering was computed from.
    """
    fields = article_text_fields(item)
    return topic_for_news(**fields), company_for_news(**fields)
