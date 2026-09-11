from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from app.config.env import BACKEND_ROOT, load_dotenv

DEFAULT_TIMEOUT = 20.0


def _as_bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class LLMSettings:
    enabled: bool
    api_key: str
    model: str
    base_url: str
    timeout: float
    cache_dir: Path

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
    )
