from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.services.llm.schemas import ArticleEnrichment

T = TypeVar("T", bound=BaseModel)


class LLMCache:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def hash_parts(self, *parts: str) -> str:
        raw = chr(10).join(parts)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def make_key(
        self,
        *,
        canonical_url: str,
        title: str,
        summary: str,
        model: str,
        prompt_version: str,
    ) -> str:
        return self.hash_parts(canonical_url, title, summary, model, prompt_version)

    def get_model(self, key: str, model_cls: type[T]) -> T | None:
        path = self.directory / f"{key}.json"
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return model_cls.model_validate(payload)
        except (OSError, ValueError, TypeError, ValidationError):
            return None

    def set_model(self, key: str, model: BaseModel) -> None:
        path = self.directory / f"{key}.json"
        path.write_text(model.model_dump_json(indent=2), encoding="utf-8", newline=chr(10))

    def get(self, key: str) -> ArticleEnrichment | None:
        return self.get_model(key, ArticleEnrichment)

    def set(self, key: str, enrichment: ArticleEnrichment) -> None:
        self.set_model(key, enrichment)
