from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class RawArticle:
    source: str
    title: str
    url: str
    published_at: datetime | None
    summary: str
