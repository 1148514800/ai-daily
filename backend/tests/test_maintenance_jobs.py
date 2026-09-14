"""Phase 10.10: the maintenance commands, their guard, and their dry runs.

The core regression lives here: with no ``DATABASE_URL`` set, running
``rebuild_search_index`` against the default database must refuse *and* leave the
file's SHA256 untouched. That is the Phase 10.9 incident reproduced.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.config import maintenance
from app.config.database_safety import DEFAULT_DATABASE_FILE
from app.config.environment import APP_ENV_DEVELOPMENT, APP_ENV_PRODUCTION
from app.config.maintenance import EXIT_ABORTED, EXIT_REFUSED
from app.db import readonly
from app.db.repositories import NewsRepository
from app.db.session import configure_database, new_session, reset_database
from app.jobs import (
    backfill_article_content,
    inspect_database,
    rebuild_digests,
    rebuild_search_index,
)
from app.models import NewsCategory, NewsItem
from app.services.news_search import SEARCH_TABLE
from tests.conftest import FROZEN_NOW


def fts_tables(path: Path) -> list[str]:
    """The search tables a file currently holds, read without creating any."""
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'news_search_fts%'"
        ).fetchall()
    finally:
        connection.close()
    return sorted(row[0] for row in rows)


def blank_database(path: Path) -> Path:
    """A real, empty SQLite file: exists, but no AI Daily schema yet."""
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
    connection.commit()
    connection.close()
    return path


def seed_article(news_id: str = "rss-1") -> NewsItem:
    return NewsItem(
        id=news_id,
        title_cn="某公司发布新模型",
        title_original="A company ships a model",
        summary="摘要",
        why_it_matters="",
        source="OpenAI",
        source_type="official",
        published_at=FROZEN_NOW.isoformat(),
        category=NewsCategory.highlight,
        tags=["OpenAI"],
        url="https://openai.com/index/model",
        content_original="正文",
    )


def scratch_db(tmp_path: Path, name: str = "scratch.db") -> Path:
    return tmp_path / name


@pytest.fixture
def isolated_backups(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Never let a test write into the repository's own backups directory."""
    directory = tmp_path / "backups"
    monkeypatch.setenv(maintenance.BACKUP_DIR_ENV, str(directory))
    return directory


# --- the incident ------------------------------------------------------------


def test_the_10_9_incident_now_refuses_and_changes_nothing(
    monkeypatch: pytest.MonkeyPatch, isolated_backups
) -> None:
    """No DATABASE_URL, target = the real database: refuse, byte for byte.

    This is the exact command that silently rewrote the production database in
    Phase 10.9. Today it must exit non-zero with the documented message, and the
    file must be bit-identical afterwards.
    """
    monkeypatch.setenv("APP_ENV", APP_ENV_DEVELOPMENT)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    before = readonly.file_sha256(DEFAULT_DATABASE_FILE)

    code = rebuild_search_index.main([])

    assert code == EXIT_REFUSED
    assert readonly.file_sha256(DEFAULT_DATABASE_FILE) == before


def test_the_incident_refusal_prints_the_documented_message(
    monkeypatch: pytest.MonkeyPatch, isolated_backups, capsys
) -> None:
    monkeypatch.setenv("APP_ENV", APP_ENV_DEVELOPMENT)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    rebuild_search_index.main([])

    output = capsys.readouterr().out
    assert "Target database looks like the production/default AI Daily database." in output
    assert "Use --allow-production if intentional." in output


def test_allow_production_backs_up_then_executes(
    monkeypatch: pytest.MonkeyPatch, isolated_backups, capsys, fake_default_database
) -> None:
    """``--allow-production`` is the documented way in, and it still backs up.

    The "production" database here is a stand-in: the sentinel is repointed at a
    temporary file, so the real code path (guard -> backup -> execute) runs in
    full without any test ever opening the real digest.
    """
    monkeypatch.setenv("APP_ENV", APP_ENV_DEVELOPMENT)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    seed_article_into(fake_default_database)

    code = rebuild_search_index.main(["--allow-production"])

    assert code == 0
    output = capsys.readouterr().out
    assert "Search index rebuilt" in output
    # A backup was taken before the write, and it landed in the chosen directory.
    backups = sorted(isolated_backups.glob("pre_rebuild_search_index_*.db"))
    assert len(backups) == 1
    assert readonly.integrity_check(backups[0]) == "ok"
    # The write really happened, so this is not passing by doing nothing.
    assert SEARCH_TABLE in fts_tables(fake_default_database)


def test_the_default_database_guard_survives_a_wrong_app_env(
    monkeypatch: pytest.MonkeyPatch, isolated_backups
) -> None:
    """``APP_ENV=development`` is not a way around the default-file sentinel."""
    monkeypatch.setenv("APP_ENV", APP_ENV_DEVELOPMENT)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./data/ai_daily.db")
    before = readonly.file_sha256(DEFAULT_DATABASE_FILE)

    assert rebuild_search_index.main([]) == EXIT_REFUSED
    assert rebuild_digests.main(["--dates", "2026-09-12"]) == EXIT_REFUSED
    assert backfill_article_content.main(["--limit", "1"]) == EXIT_REFUSED
    assert readonly.file_sha256(DEFAULT_DATABASE_FILE) == before


# --- the header and precedence ----------------------------------------------


def test_every_command_prints_environment_database_and_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_backups, capsys
) -> None:
    monkeypatch.setenv("APP_ENV", APP_ENV_DEVELOPMENT)
    url = f"sqlite:///{scratch_db(tmp_path).as_posix()}"

    for code, argv, run in (
        (0, ["--dry-run", "--database-url", url], rebuild_search_index.main),
        (0, ["--dates", "2026-09-12", "--dry-run", "--database-url", url], rebuild_digests.main),
        (
            0,
            ["--limit", "1", "--dry-run", "--database-url", url],
            backfill_article_content.main,
        ),
    ):
        assert run(argv) == code
        output = capsys.readouterr().out
        assert "Environment:" in output
        assert "Database:" in output
        assert "Mode:" in output
        assert "dry-run" in output


def test_header_shows_the_resolved_path_not_the_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_backups, capsys
) -> None:
    monkeypatch.setenv("APP_ENV", APP_ENV_DEVELOPMENT)
    database = scratch_db(tmp_path)

    rebuild_search_index.main(["--dry-run", "--database-url", f"sqlite:///{database.as_posix()}"])

    output = capsys.readouterr().out
    assert str(database.resolve()) in output
    assert "sqlite:///" not in output


def test_cli_url_beats_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_backups, capsys
) -> None:
    monkeypatch.setenv("APP_ENV", APP_ENV_DEVELOPMENT)
    from_env = scratch_db(tmp_path, "from_env.db")
    from_cli = scratch_db(tmp_path, "from_cli.db")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{from_env.as_posix()}")

    rebuild_search_index.main(
        ["--dry-run", "--database-url", f"sqlite:///{from_cli.as_posix()}"]
    )

    output = capsys.readouterr().out
    assert str(from_cli.resolve()) in output
    assert str(from_env.resolve()) not in output


def test_a_bare_path_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_backups, capsys
) -> None:
    monkeypatch.setenv("APP_ENV", APP_ENV_DEVELOPMENT)
    database = scratch_db(tmp_path)

    assert rebuild_search_index.main(["--dry-run", "--database-url", str(database)]) == 0
    assert str(database.resolve()) in capsys.readouterr().out


# --- dry run -----------------------------------------------------------------


def test_dry_run_indexes_nothing_and_creates_no_fts_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_backups, capsys
) -> None:
    """The three prohibitions: no data, no permanent FTS table, no schema work."""
    monkeypatch.setenv("APP_ENV", APP_ENV_DEVELOPMENT)
    database = seed_scratch_database(tmp_path)
    before = readonly.file_sha256(database)

    code = rebuild_search_index.main(["--dry-run", "--database-url", f"sqlite:///{database.as_posix()}"])

    assert code == 0
    assert readonly.file_sha256(database) == before
    assert fts_tables(database) == []
    assert "Would index: 1 articles" in capsys.readouterr().out


def test_dry_run_digest_rebuild_writes_no_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_backups, capsys
) -> None:
    monkeypatch.setenv("APP_ENV", APP_ENV_DEVELOPMENT)
    database = seed_scratch_database(tmp_path)
    before = readonly.file_sha256(database)

    code = rebuild_digests.main(
        ["--dates", "2026-09-11", "--dry-run", "--database-url", f"sqlite:///{database.as_posix()}"]
    )

    assert code == 0
    assert readonly.file_sha256(database) == before
    assert "Dry run: no changes made" in capsys.readouterr().out


def test_dry_run_backfill_extracts_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_backups, capsys
) -> None:
    monkeypatch.setenv("APP_ENV", APP_ENV_DEVELOPMENT)
    database = seed_scratch_database(tmp_path, with_body=False)
    before = readonly.file_sha256(database)

    def explode(*args, **kwargs):
        raise AssertionError("a dry run must not fetch or extract a page")

    monkeypatch.setattr(backfill_article_content, "extract_article", explode)

    code = backfill_article_content.main(
        ["--limit", "5", "--dry-run", "--database-url", f"sqlite:///{database.as_posix()}"]
    )

    assert code == 0
    assert readonly.file_sha256(database) == before
    output = capsys.readouterr().out
    assert "Would scan: 1" in output


def test_dry_run_reports_rather_than_creates_a_missing_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_backups, capsys
) -> None:
    monkeypatch.setenv("APP_ENV", APP_ENV_DEVELOPMENT)
    database = scratch_db(tmp_path, "never_created.db")

    assert rebuild_search_index.main(["--dry-run", "--database-url", str(database)]) == 0

    assert not database.exists()
    assert "Would index: 0 articles" in capsys.readouterr().out


# --- abort paths -------------------------------------------------------------


def test_a_failed_backup_aborts_the_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_backups, capsys
) -> None:
    """Backup failure must stop the run: validate -> backup -> execute."""
    monkeypatch.setenv("APP_ENV", APP_ENV_PRODUCTION)
    database = seed_scratch_database(tmp_path, with_fts=False)
    before = readonly.file_sha256(database)
    isolated_backups.parent.mkdir(parents=True, exist_ok=True)
    isolated_backups.write_bytes(b"blocks the backup directory")

    code = rebuild_search_index.main(
        ["--allow-production", "--database-url", f"sqlite:///{database.as_posix()}"]
    )

    assert code == EXIT_ABORTED
    assert "Aborted" in capsys.readouterr().out
    assert readonly.file_sha256(database) == before
    assert fts_tables(database) == []


def test_a_corrupt_database_aborts_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_backups, capsys
) -> None:
    monkeypatch.setenv("APP_ENV", APP_ENV_PRODUCTION)
    database = tmp_path / "corrupt.db"
    database.write_bytes(b"not a sqlite database")

    code = rebuild_search_index.main(
        ["--allow-production", "--database-url", f"sqlite:///{database.as_posix()}"]
    )

    assert code == EXIT_ABORTED
    assert "Aborted" in capsys.readouterr().out
    assert database.read_bytes() == b"not a sqlite database"


# --- the jobs still do their job --------------------------------------------


def test_rebuild_search_index_still_indexes_a_scratch_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_backups, capsys
) -> None:
    monkeypatch.setenv("APP_ENV", APP_ENV_DEVELOPMENT)
    database = seed_scratch_database(tmp_path, with_fts=False)
    url = f"sqlite:///{database.as_posix()}"

    assert rebuild_search_index.main(["--database-url", url]) == 0

    assert SEARCH_TABLE in fts_tables(database)
    assert "Articles: 1" in capsys.readouterr().out
    # A scratch database needs no production guard and no backup.
    assert list(isolated_backups.glob("*.db")) == []


def test_rebuild_digests_still_rebuilds_a_scratch_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_backups, capsys
) -> None:
    monkeypatch.setenv("APP_ENV", APP_ENV_DEVELOPMENT)
    database = seed_scratch_database(tmp_path)
    url = f"sqlite:///{database.as_posix()}"

    assert rebuild_digests.main(["--dates", "2026-09-11", "--database-url", url]) == 0

    assert "2026-09-11:" in capsys.readouterr().out


def test_backfill_still_fills_a_scratch_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_backups, capsys
) -> None:
    monkeypatch.setenv("APP_ENV", APP_ENV_DEVELOPMENT)
    database = seed_scratch_database(tmp_path, with_body=False)
    url = f"sqlite:///{database.as_posix()}"
    monkeypatch.setattr(
        backfill_article_content,
        "extract_article",
        lambda **kwargs: _article_content(),
    )

    assert backfill_article_content.main(["--database-url", url]) == 0

    output = capsys.readouterr().out
    assert "Filled: 1" in output
    assert "正文" in readonly.scalar(database, "SELECT content_original FROM news_articles")


def _article_content():
    from app.services.article_extractor import ArticleContent

    return ArticleContent(text="网上抓到的正文", language="zh", method="web")


def test_jobs_are_idempotent_on_a_scratch_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_backups
) -> None:
    """Running a rebuild twice leaves the same state, as documented."""
    monkeypatch.setenv("APP_ENV", APP_ENV_DEVELOPMENT)
    database = seed_scratch_database(tmp_path)
    url = f"sqlite:///{database.as_posix()}"

    rebuild_search_index.main(["--database-url", url])
    first = readonly.scalar(database, f'SELECT COUNT(*) FROM "{SEARCH_TABLE}"')
    rebuild_search_index.main(["--database-url", url])
    second = readonly.scalar(database, f'SELECT COUNT(*) FROM "{SEARCH_TABLE}"')

    assert first == second == 1


# --- inspect_database --------------------------------------------------------


def test_inspect_database_is_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setenv("APP_ENV", APP_ENV_DEVELOPMENT)
    database = seed_scratch_database(tmp_path)
    before = readonly.file_sha256(database)

    assert inspect_database.main(["--database-url", f"sqlite:///{database.as_posix()}"]) == 0

    assert readonly.file_sha256(database) == before


def test_inspect_database_creates_nothing_on_an_unindexed_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """No FTS table, no schema: reading must not initialise anything."""
    monkeypatch.setenv("APP_ENV", APP_ENV_DEVELOPMENT)
    database = seed_scratch_database(tmp_path, with_fts=False)
    before = readonly.file_sha256(database)

    assert inspect_database.main(["--database-url", str(database)]) == 0

    assert fts_tables(database) == []
    assert readonly.file_sha256(database) == before
    assert "(none)" in capsys.readouterr().out


def test_inspect_database_reports_the_documented_sections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setenv("APP_ENV", APP_ENV_DEVELOPMENT)
    database = seed_scratch_database(tmp_path)

    assert inspect_database.main(["--database-url", str(database)]) == 0

    output = capsys.readouterr().out
    for label in (
        "Path:",
        "Size:",
        "SHA256:",
        "Integrity:",
        "Foreign key check:",
        "Business table counts",
        "FTS tables",
    ):
        assert label in output, label


def test_inspect_database_reports_a_missing_file(tmp_path: Path, capsys) -> None:
    missing = tmp_path / "absent.db"

    assert inspect_database.main(["--database-url", str(missing)]) == 0

    assert "does not exist yet" in capsys.readouterr().out


# --- release_check -----------------------------------------------------------


def test_release_check_is_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.jobs import release_check

    monkeypatch.setenv("APP_ENV", APP_ENV_DEVELOPMENT)
    database = seed_scratch_database(tmp_path)
    before = readonly.file_sha256(database)

    assert release_check.main(["--database-url", str(database)]) == 0

    assert readonly.file_sha256(database) == before


def test_release_check_creates_no_fts_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.jobs import release_check

    monkeypatch.setenv("APP_ENV", APP_ENV_DEVELOPMENT)
    database = seed_scratch_database(tmp_path, with_fts=False)

    assert release_check.main(["--database-url", str(database)]) == 0

    assert fts_tables(database) == []


def test_release_check_reports_pass_warn_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from app.jobs import release_check

    monkeypatch.setenv("APP_ENV", APP_ENV_DEVELOPMENT)
    monkeypatch.setenv("APP_TIMEZONE", "Asia/Shanghai")
    database = seed_scratch_database(tmp_path)

    assert release_check.main(["--database-url", str(database)]) == 0

    output = capsys.readouterr().out
    assert "PASS" in output
    assert "FAIL" not in output


def test_release_check_fails_on_an_unknown_app_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from app.jobs import release_check

    monkeypatch.setenv("APP_ENV", "prodution")
    database = seed_scratch_database(tmp_path)

    assert release_check.main(["--database-url", str(database)]) == 1

    output = capsys.readouterr().out
    assert "FAIL" in output
    assert "APP_ENV" in output


def test_release_check_fails_on_an_unusable_timezone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from app.jobs import release_check

    monkeypatch.setenv("APP_ENV", APP_ENV_DEVELOPMENT)
    monkeypatch.setenv("APP_TIMEZONE", "Mars/Olympus")
    database = seed_scratch_database(tmp_path)

    assert release_check.main(["--database-url", str(database)]) == 1
    assert "APP_TIMEZONE" in capsys.readouterr().out


def test_release_check_reports_a_corrupt_database_rather_than_crashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from app.jobs import release_check

    monkeypatch.setenv("APP_ENV", APP_ENV_DEVELOPMENT)
    database = tmp_path / "corrupt.db"
    database.write_bytes(b"definitely not a database")

    assert release_check.main(["--database-url", str(database)]) == 1
    output = capsys.readouterr().out
    assert "Database integrity" in output
    assert "FAIL" in output


def test_release_check_reports_the_search_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from app.jobs import release_check

    monkeypatch.setenv("APP_ENV", APP_ENV_DEVELOPMENT)
    database = seed_scratch_database(tmp_path)

    release_check.main(["--database-url", str(database)])

    assert "Search backend" in capsys.readouterr().out


def test_release_check_makes_no_network_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No RSS and no LLM request, whatever the configuration says."""
    from app.jobs import release_check

    monkeypatch.setenv("APP_ENV", APP_ENV_DEVELOPMENT)
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("LLM_API_KEY", "sk-not-a-real-key")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:1/v1")
    database = seed_scratch_database(tmp_path)

    def explode(*args, **kwargs):
        raise AssertionError("release_check must not touch the network")

    monkeypatch.setattr("app.collectors.rss.fetch_rss_text", explode)
    monkeypatch.setattr("app.services.llm.client.LLMClient.complete", explode)

    assert release_check.main(["--database-url", str(database)]) == 0


def test_release_check_warns_when_the_scheduler_is_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from app.jobs import release_check

    monkeypatch.setenv("APP_ENV", APP_ENV_DEVELOPMENT)
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    database = seed_scratch_database(tmp_path)

    assert release_check.main(["--database-url", str(database)]) == 0
    output = capsys.readouterr().out
    assert "WARN" in output
    assert "SCHEDULER_ENABLED=false" in output


# --- helpers -----------------------------------------------------------------


def seed_scratch_database(
    tmp_path: Path, *, with_body: bool = True, with_fts: bool = False
) -> Path:
    """A scratch database carrying one article, built through the app itself."""
    database = tmp_path / "scratch.db"
    url = f"sqlite:///{database.as_posix()}"
    configure_database(url)
    try:
        from app.db.session import init_db

        init_db()
        item = seed_article()
        if not with_body:
            item = item.model_copy(update={"content_original": ""})
        session = new_session()
        try:
            NewsRepository(session).upsert_many([item])
            session.commit()
        finally:
            session.close()
        if not with_fts:
            session = new_session()
            try:
                from sqlalchemy import text

                session.execute(text(f'DROP TABLE IF EXISTS "{SEARCH_TABLE}"'))
                session.commit()
            finally:
                session.close()
    finally:
        reset_database()
    return database

def seed_article_into(path: Path) -> None:
    """Initialise ``path`` with one article, using a standalone engine.

    Deliberately not ``configure_database``: while the sentinel is repointed at
    this file, the test guard would (correctly) refuse to route the app at it.
    A private engine keeps the seeding honest without weakening that guard.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import app.db.models  # noqa: F401  (register mappers)
    from app.db.base import Base

    engine = create_engine(f"sqlite:///{path.as_posix()}")
    try:
        Base.metadata.create_all(bind=engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
        session = factory()
        try:
            NewsRepository(session).upsert_many([seed_article()])
            session.commit()
        finally:
            session.close()
    finally:
        engine.dispose()


def test_allow_production_is_the_only_way_past_the_sentinel(
    monkeypatch: pytest.MonkeyPatch, isolated_backups, fake_default_database
) -> None:
    """Without the flag the very same target is refused, so the flag is load-bearing."""
    monkeypatch.setenv("APP_ENV", APP_ENV_DEVELOPMENT)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    seed_article_into(fake_default_database)
    before = readonly.file_sha256(fake_default_database)

    assert rebuild_search_index.main([]) == EXIT_REFUSED
    assert readonly.file_sha256(fake_default_database) == before
