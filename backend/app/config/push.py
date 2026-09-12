from __future__ import annotations

import os

from app.config.env import load_dotenv

DEFAULT_EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
DEFAULT_CHANNEL_ID = "daily-digest"
# Expo accepts at most 100 messages per request.
MAX_MESSAGES_PER_REQUEST = 100


def push_enabled() -> bool:
    """Push stays off unless explicitly turned on, so a fresh checkout always boots."""
    load_dotenv()
    raw = os.getenv("PUSH_ENABLED", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def expo_push_url() -> str:
    load_dotenv()
    return os.getenv("EXPO_PUSH_URL", "").strip() or DEFAULT_EXPO_PUSH_URL


def notification_channel_id() -> str:
    return DEFAULT_CHANNEL_ID
