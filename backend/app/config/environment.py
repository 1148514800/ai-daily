"""Which environment this process runs in (``APP_ENV``).

One place decides the environment, so the API, the maintenance commands and the
test suite cannot disagree about it:

* ``development`` - the default. Local work, loose CORS, the developer database.
* ``test``        - pytest. Must never open the production database.
* ``production``  - the real digest. Write maintenance tasks refuse to run here
  unless ``--allow-production`` is given.

An unrecognised value falls back to ``development`` and is logged, and
``release_check`` reports it, so a typo like ``prodution`` cannot look like a
deliberate production setting without being visible.
"""

from __future__ import annotations

import logging
import os

from app.config.env import load_dotenv

APP_ENV_DEVELOPMENT = "development"
APP_ENV_TEST = "test"
APP_ENV_PRODUCTION = "production"

APP_ENV_VALUES = (APP_ENV_DEVELOPMENT, APP_ENV_TEST, APP_ENV_PRODUCTION)
DEFAULT_APP_ENV = APP_ENV_DEVELOPMENT

logger = logging.getLogger(__name__)


def configured_app_env() -> str:
    """The raw ``APP_ENV`` value, lower-cased, possibly empty or unknown."""
    load_dotenv()
    return os.getenv("APP_ENV", "").strip().lower()


def app_env() -> str:
    """The environment to behave as. Always one of ``APP_ENV_VALUES``."""
    raw = configured_app_env()
    if not raw:
        return DEFAULT_APP_ENV
    if raw not in APP_ENV_VALUES:
        logger.warning("unknown APP_ENV %r; behaving as %s", raw, DEFAULT_APP_ENV)
        return DEFAULT_APP_ENV
    return raw


def is_development() -> bool:
    return app_env() == APP_ENV_DEVELOPMENT


def is_test() -> bool:
    return app_env() == APP_ENV_TEST


def is_production() -> bool:
    return app_env() == APP_ENV_PRODUCTION


def is_valid_app_env(raw: str) -> bool:
    """Whether a raw value is recognised, without silently defaulting it."""
    return raw.strip().lower() in APP_ENV_VALUES


def set_app_env(value: str) -> None:
    """Force the environment for this process. Used by scripts and tests."""
    os.environ["APP_ENV"] = value.strip().lower()


def environment_label() -> str:
    """``APP_ENV`` for humans, marking a defaulted value as such."""
    if not configured_app_env():
        return f"{DEFAULT_APP_ENV} (default)"
    return app_env()
