from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.services.llm.schemas import ArticleEnrichment


class LLMCache:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def make_key(
        self,
        *,
        canonical_url: str,
        title: str,
        summary: str,
        model: str,
        prompt_version: str,
    ) -> str:
        raw = "\n".join([canonical_url, title, summary, model, prompt_version])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, key: str) -> ArticleEnrichment | None:
        path = self.directory / f"{key}.json"
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return ArticleEnrichment.model_validate(payload)
        except (OSError, ValueError, TypeError):
            return None

    def set(self, key: str, enrichment: ArticleEnrichment) -> None:
        path = self.directory / f"{key}.json"
        path.write_text(
            enrichment.model_dump_json(indent=2),
            encoding="utf-8",
            newline="\n",
        )
