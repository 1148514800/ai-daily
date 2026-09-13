"""Ranking configuration shared by the ranker, the API, and the store.

Only the values that more than one layer needs live here. The weights,
penalties, and thresholds of the ranking itself stay in
``app.services.news_ranker.RankingSettings``, next to the code that applies
them, so a tuning change and its affected tests stay in one file.
"""

from __future__ import annotations

import os

from app.config.env import load_dotenv

# How many leading stories the daily digest marks as a top story. The tail is
# kept: it is the "more news" list, not discarded content.
DEFAULT_TOP_STORY_LIMIT = 10


def top_story_limit() -> int:
    """The top-story count, overridable so a short digest can be tuned."""
    load_dotenv()
    raw = (os.getenv("TOP_STORY_LIMIT") or "").strip()
    if not raw:
        return DEFAULT_TOP_STORY_LIMIT
    try:
        parsed = int(raw)
    except ValueError:
        return DEFAULT_TOP_STORY_LIMIT
    return parsed if parsed > 0 else DEFAULT_TOP_STORY_LIMIT
