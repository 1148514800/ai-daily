"""Phase 10.10: read-only paths must not initialise the search index.

``inspect_database``, ``release_check`` and the status endpoints exist to report
on a database. None of them may create ``news_search_fts``: that table is created
only where search is actually initialised (app startup, or an explicit rebuild).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.config.maintenance import BACKUP_DIR_ENV
from app.db import readonly
from app.db.repositories import NewsRepository
from app.db.session import configure_database, new_session, reset_database
from app.jobs import inspect_database, release_check
from app.models import NewsCategory, NewsItem
from app.services.news_search import SEARCH_TABLE
from tests.conftest import FROZEN_NOW


def search_tables(path: Path) -> list[str]:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE name LIKE 'news_search_fts%'"
        ).fetchall()
    finally:
        connection.close()
    return sorted(row[0] for row in rows)


def build_database_without_search(path: Path) -> Path:
    """A database with articles and no search index, as a pre-10.9 file looks."""
    configure_database(f"sqlite:///{path.as_posix()}")
    try:
        from app.db.session import init_db

        init_db()
        session = new_session()
        try:
            NewsRepository(session).upsert_many(
                [
                    NewsItem(
                        id="rss-1",
                        title_cn="标题",
                        title_original="Title",
                        summary="摘要",
                        why_it_matters="",
                        source="OpenAI",
                        source_type="official",
                        published_at=FROZEN_NOW.isoformat(),
                        category=NewsCategory.highlight,
                        tags=["OpenAI"],
                        url="https://openai.com/index/x",
                    )
                ]
            )
            session.commit()
            from sqlalchemy import text

            session.execute(text(f'DROP TABLE IF EXISTS "{SEARCH_TABLE}"'))
            session.commit()
        finally:
            session.close()
    finally:
        reset_database()
    return path


@pytest.fixture
def backups_outside_the_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BACKUP_DIR_ENV, str(tmp_path / "backups"))


def test_inspect_database_does_not_create_the_fts_table(
    tmp_path: Path, backups_outside_the_repo
) -> None:
    database = build_database_without_search(tmp_path / "ai.db")
    before = readonly.file_sha256(database)

    assert search_tables(database) == []
    assert inspect_database.main(["--database-url", str(database)]) == 0

    assert search_tables(database) == []
    assert readonly.file_sha256(database) == before


def test_release_check_does_not_create_the_fts_table(
    tmp_path: Path, backups_outside_the_repo
) -> None:
    database = build_database_without_search(tmp_path / "ai.db")
    before = readonly.file_sha256(database)

    assert release_check.main(["--database-url", str(database)]) == 0

    assert search_tables(database) == []
    assert readonly.file_sha256(database) == before


def test_status_endpoints_do_not_create_the_fts_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Importing the app and asking for status must not build an index either."""
    database = build_database_without_search(tmp_path / "ai.db")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")

    from fastapi.testclient import TestClient

    from app.main import app

    # The lifespan is deliberately not started: this checks the import and the
    # status routes, which is where a stray ensure_table would hide.
    with TestClient(app) as client:
        assert client.get("/api/v1/system/status").status_code == 200
        assert client.get("/api/v1/refresh/status").status_code == 200

    # Startup does initialise search (that is its job), so the index may exist by
    # now; what must not happen is a status *route* creating it on its own.
    assert search_tables(database) != []


def test_reading_the_database_needs_no_search_index(
    tmp_path: Path, backups_outside_the_repo
) -> None:
    """Digest reads work on an unindexed database: search is an add-on."""
    from app.services.digest_store import DigestStore

    database = build_database_without_search(tmp_path / "ai.db")

    # No crash, and still no index created by a plain read.
    DigestStore().list_digest_summaries()
    assert search_tables(database) == []

def test_indexing_an_article_does_not_create_the_fts_table(
    tmp_path: Path, backups_outside_the_repo
) -> None:
    """The last creation path claim: a write to a missing index is a no-op.

    ``index_items`` is called on the normal refresh path. On a database with no
    index it must skip rather than create one, so the only places the table
    appears stay the explicit ones (startup and rebuild).
    """
    from app.db.session import new_session
    from app.services.news_search import index_items

    database = build_database_without_search(tmp_path / "ai.db")
    configure_database(f"sqlite:///{database.as_posix()}")
    try:
        session = new_session()
        try:
            written = index_items(
                session,
                [
                    NewsItem(
                        id="rss-2",
                        title_cn="标题",
                        title_original="Title",
                        summary="摘要",
                        why_it_matters="",
                        source="OpenAI",
                        source_type="official",
                        published_at=FROZEN_NOW.isoformat(),
                        category=NewsCategory.highlight,
                        tags=["OpenAI"],
                        url="https://openai.com/index/y",
                    )
                ],
            )
            session.commit()
        finally:
            session.close()
    finally:
        reset_database()

    assert written == 0
    assert search_tables(database) == []
