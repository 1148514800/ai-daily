from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class RawArticle:
    source_id: str
    source: str
    source_type: str
    title: str
    url: str
    canonical_url: str
    published_at: datetime | None
    summary: str
