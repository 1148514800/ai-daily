from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config.env import BACKEND_ROOT, load_dotenv
from app.db.base import Base

DEFAULT_DATABASE_URL = "sqlite:///./data/ai_daily.db"

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None
_database_url: str | None = None


def database_url() -> str:
    load_dotenv()
    return os.getenv("DATABASE_URL", "").strip() or DEFAULT_DATABASE_URL


def _resolve_url(url: str) -> str:
    """Resolve relative SQLite paths against the backend root, not the CWD.

    The env var stays portable; only the runtime path is absolute.
    """
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return url
    raw_path = url[len(prefix) :]
    if raw_path in {"", ":memory:"} or raw_path.startswith("/"):
        return url
    path = (BACKEND_ROOT / raw_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"{prefix}{path}"


def _configure_sqlite(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def get_engine() -> Engine:
    global _engine, _database_url
    resolved = _resolve_url(database_url())
    if _engine is None or _database_url != resolved:
        if _engine is not None:
            _engine.dispose()
        is_sqlite = resolved.startswith("sqlite")
        connect_args = {"check_same_thread": False} if is_sqlite else {}
        _engine = create_engine(resolved, connect_args=connect_args, future=True)
        if is_sqlite:
            _configure_sqlite(_engine)
        _database_url = resolved
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory, _database_url
    get_engine()
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _session_factory


def configure_database(url: str) -> None:
    """Point the process at another database. Used by tests."""
    global _engine, _session_factory, _database_url
    resolved = _resolve_url(url)
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
    _database_url = None
    os.environ["DATABASE_URL"] = url


def reset_database() -> None:
    """Drop cached engine state so the next call re-reads DATABASE_URL."""
    global _engine, _session_factory, _database_url
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
    _database_url = None


def init_db() -> None:
    """Create tables. No migration system in this phase."""
    import app.db.models  # noqa: F401  (register mappers)

    Base.metadata.create_all(bind=get_engine())


def new_session() -> Session:
    return get_session_factory()()


def session_scope() -> Iterator[Session]:
    session = new_session()
    try:
        yield session
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    session = new_session()
    try:
        yield session
    finally:
        session.close()
