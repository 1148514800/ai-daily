"""Configuration for Tavily Web Discovery, the dynamic layer beside the fixed sources.

The fixed sources in ``app/config/sources.py`` are the reliable trunk of AI Daily:
they are curated, first-party where possible, and a failure in one of them is a
failure in one feed. They are also *fixed*, which is the gap this module fills —
a new model, a new robotics lab or a breaking story on an outlet nobody
configured will never appear in the digest no matter how important it is.

Web Discovery narrows that gap without becoming a second trunk. Tavily is asked
the same ten topic queries on every refresh, and whatever it finds is treated as
a *candidate*: it still has to survive the same pipeline as everything else
(dedupe, extraction, LLM importance, media selection, ranking). Discovery adds
recall; it never decides what the digest says.

**Off by default.** ``WEB_DISCOVERY_ENABLED`` is ``false`` in
``.env.example``, so a deployment that configures nothing behaves exactly as it
did before this module existed — no API key is needed and no request is made.

The queries are fixed and the sources are not. That is the entire point: a fixed
query set over an open web is what lets the engine surface a page from a company
AI Daily has never heard of, which a fixed source list structurally cannot do.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from app.config.env import load_dotenv

# Which dynamic discovery backend to use. Only Tavily is implemented; the setting
# exists so a second provider can be added without changing the caller, and an
# unknown value disables discovery rather than silently picking one.
PROVIDER_TAVILY = "tavily"
KNOWN_PROVIDERS = (PROVIDER_TAVILY,)

DEFAULT_ENABLED = False
DEFAULT_PROVIDER = PROVIDER_TAVILY

# Per query and per refresh. 10 matches the benchmark so a production run is
# directly comparable with the numbers the decision was made on.
DEFAULT_RESULTS_PER_QUERY = 10

# The cap on what may enter article extraction and the LLM. A refresh that
# searched 10 queries can return ~100 results; extracting and enriching all of
# them would cost far more than the discovery is worth, so the funnel narrows to
# this many before the real pipeline starts. 24 is about one extra digest worth
# of candidates.
DEFAULT_MAX_CANDIDATES = 24

# How many candidates one hostname may contribute. A portal that happens to rank
# well on several queries must not fill the whole allowance — that is exactly the
# Baidu/Aliyun failure mode the benchmark documented.
DEFAULT_MAX_PER_DOMAIN = 2

# Tavily's own documented server behaviour is fast; the benchmark answered in
# about a second. 15s is generous for one query while keeping ten sequential
# queries inside a refresh.
DEFAULT_TIMEOUT = 15.0

# Reciprocal Rank Fusion constant. RRF scores a document by summing
# ``1 / (k + rank)`` over the queries that returned it, so a hit near the top of
# one list and a hit that several different queries all found both score well.
# ``k`` damps the difference between the first few ranks (the standard value from
# the original RRF paper); changing it changes how much a single strong rank can
# outweigh agreement across queries.
RRF_K = 60

# Tavily's maximum for one request. Asking for more is a request the service
# cannot answer as written, so it is clamped rather than sent.
MAX_RESULTS_PER_QUERY_LIMIT = 20

# The ten topics the product actually reports on: models, agents, coding agents,
# humanoid robots and chips, in both Chinese and English, plus one query naming
# the Chinese vendors the fixed sources cover least well. They live in
# production code rather than in the benchmark probe because the refresh depends
# on them; the probes import them, never the other way round.
DISCOVERY_QUERIES: tuple[str, ...] = (
    "AI 人工智能 最新发布",
    "大模型 LLM 最新发布",
    "AI Agent 最新发布",
    "AI 编程 Agent 最新发布",
    "人形机器人 具身智能 最新发布",
    "AI 芯片 推理 最新发布",
    "DeepSeek 豆包 智谱 MiniMax 最新",
    "new AI model release",
    "AI agent latest release",
    "humanoid robot AI latest",
)

# Surfaces that are not articles at all, so the article extractor has nothing to
# read and the LLM has nothing to summarise. Deliberately tiny and limited to
# pages that are structurally posts rather than pages: this is not a quality
# blacklist. Portals, aggregators and blogs are judged downstream by importance,
# media selection and ranking, which is where that judgement belongs — a
# discovery layer that maintained a long domain blacklist would just be a
# second, worse source configuration.
NON_ARTICLE_DOMAINS: tuple[str, ...] = (
    "facebook.com",
    "instagram.com",
)

# Enables per-candidate KEEP/DROP logging. Off by default so a normal refresh
# logs one summary line.
DEBUG_ENV = "AI_DAILY_DEBUG_WEB_DISCOVERY"


def _flag(name: str, default: bool) -> bool:
    """A boolean environment flag, tolerant of the usual spellings."""
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _positive_int(name: str, default: int, *, maximum: int | None = None) -> int:
    """A positive integer setting; anything unparseable keeps the default.

    A typo must not disable the cap it was meant to tighten, so an invalid value
    falls back rather than becoming 0.
    """
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if value <= 0:
        return default
    if maximum is not None and value > maximum:
        return maximum
    return value


def _float_seconds(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


@dataclass(frozen=True)
class WebDiscoverySettings:
    """One refresh's discovery configuration."""

    enabled: bool = DEFAULT_ENABLED
    provider: str = DEFAULT_PROVIDER
    api_key: str = ""
    results_per_query: int = DEFAULT_RESULTS_PER_QUERY
    max_candidates: int = DEFAULT_MAX_CANDIDATES
    max_per_domain: int = DEFAULT_MAX_PER_DOMAIN
    timeout: float = DEFAULT_TIMEOUT
    debug: bool = False

    @property
    def runnable(self) -> bool:
        """Whether a discovery request should actually be made.

        Enabled *and* configured: an enabled provider with no key is a
        configuration mistake that is reported once and then skipped, never a
        reason to fail the refresh.
        """
        return self.enabled and self.provider in KNOWN_PROVIDERS and bool(self.api_key)


def load_web_discovery_settings() -> WebDiscoverySettings:
    """Read the discovery settings from the environment.

    Reads ``.env`` first, matching every other configuration module, so a
    development machine behaves the same whether the value came from the shell
    or from ``backend/.env``.
    """
    load_dotenv()
    provider = (os.getenv("WEB_DISCOVERY_PROVIDER") or "").strip().lower() or DEFAULT_PROVIDER
    return WebDiscoverySettings(
        enabled=_flag("WEB_DISCOVERY_ENABLED", DEFAULT_ENABLED),
        provider=provider,
        api_key=(os.getenv("TAVILY_API_KEY") or "").strip(),
        results_per_query=_positive_int(
            "WEB_DISCOVERY_RESULTS_PER_QUERY",
            DEFAULT_RESULTS_PER_QUERY,
            maximum=MAX_RESULTS_PER_QUERY_LIMIT,
        ),
        max_candidates=_positive_int("WEB_DISCOVERY_MAX_CANDIDATES", DEFAULT_MAX_CANDIDATES),
        max_per_domain=_positive_int("WEB_DISCOVERY_MAX_PER_DOMAIN", DEFAULT_MAX_PER_DOMAIN),
        timeout=_float_seconds("WEB_DISCOVERY_TIMEOUT", DEFAULT_TIMEOUT),
        debug=_flag(DEBUG_ENV, False),
    )