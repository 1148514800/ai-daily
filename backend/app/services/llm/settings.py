from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from app.config.env import BACKEND_ROOT, load_dotenv

DEFAULT_TIMEOUT = 20.0

# How much of the original body is sent to the LLM. The database keeps the whole
# article; only the prompt is trimmed, and the limit lives here so no call site
# hard-codes a length of its own.
DEFAULT_CONTENT_MAX_CHARS = 6000


def _as_bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: str | None, default: int) -> int:
    try:
        parsed = int((value or "").strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


@dataclass(frozen=True)
class LLMSettings:
    enabled: bool
    api_key: str
    model: str
    base_url: str
    timeout: float
    cache_dir: Path
    # Maximum number of body characters sent per article. 0 means no trimming.
    content_max_chars: int = DEFAULT_CONTENT_MAX_CHARS

    @property
    def available(self) -> bool:
        return bool(self.enabled and self.api_key and self.model and self.base_url)


def load_llm_settings() -> LLMSettings:
    load_dotenv()
    cache_dir = Path(os.getenv("LLM_CACHE_DIR") or (BACKEND_ROOT / ".cache" / "llm"))
    if not cache_dir.is_absolute():
        cache_dir = BACKEND_ROOT / cache_dir
    return LLMSettings(
        enabled=_as_bool(os.getenv("LLM_ENABLED")),
        api_key=(os.getenv("LLM_API_KEY") or "").strip(),
        model=(os.getenv("LLM_MODEL") or "").strip(),
        base_url=(os.getenv("LLM_BASE_URL") or "").strip(),
        timeout=DEFAULT_TIMEOUT,
        cache_dir=cache_dir,
        content_max_chars=_as_int(os.getenv("LLM_CONTENT_MAX_CHARS"), DEFAULT_CONTENT_MAX_CHARS),
    )
