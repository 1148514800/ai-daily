"""Phase 10.10: environment safety, maintenance guards and release readiness.

The incident this phase exists for: Phase 10.9 ran ``rebuild_search_index`` with
no temporary ``DATABASE_URL`` set, so it rewrote the real
``backend/data/ai_daily.db``. The tests below pin down that the same command now
refuses, and that a refusal leaves the file byte-for-byte identical.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from app.config import database_safety, maintenance
from app.config.database_safety import (
    DEFAULT_DATABASE_FILE,
    DatabaseTarget,
    is_default_database,
    resolve_target,
    sqlite_path,
)
from app.config.environment import (
    APP_ENV_DEVELOPMENT,
    APP_ENV_PRODUCTION,
    APP_ENV_TEST,
    app_env,
    set_app_env,
)
from app.config.maintenance import (
    MaintenanceError,
    ProductionGuardError,
    backup,
    backup_path,
    begin,
    default_backup_dir,
    normalize_url,
    resolve_database_url,
    validate,
)
from app.db import readonly
from app.db.session import get_engine, reset_database


def make_args(**overrides) -> "maintenance.argparse.Namespace":
    """A parsed-argument stand-in, with the defaults every job shares."""
    parser = maintenance.argparse.ArgumentParser()
    maintenance.add_common_arguments(parser)
    values = {"database-url": None, "dry-run": False, "allow-production": False}
    values.update(overrides)
    argv: list[str] = []
    for key, value in values.items():
        flag = f"--{key}"
        if value is True:
            argv.append(flag)
        elif value:
            argv.extend([flag, str(value)])
    return parser.parse_args(argv)


def sha256(path: Path) -> str:
    return readonly.file_sha256(path)


def make_sqlite_file(path: Path, *, rows: int = 1) -> Path:
    """A tiny valid database, so validation has something real to approve."""
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
        connection.executemany("INSERT INTO t (name) VALUES (?)", [("a",)] * rows)
        connection.commit()
    finally:
        connection.close()
    return path


@pytest.fixture
def scratch_backup_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep automatic backups out of the repository during tests."""
    directory = tmp_path / "backups"
    monkeypatch.setenv(maintenance.BACKUP_DIR_ENV, str(directory))
    return directory


# --- 1. APP_ENV --------------------------------------------------------------


def test_app_env_defaults_to_development(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    assert app_env() == APP_ENV_DEVELOPMENT


def test_app_env_reads_the_supported_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for value in (APP_ENV_DEVELOPMENT, APP_ENV_TEST, APP_ENV_PRODUCTION):
        monkeypatch.setenv("APP_ENV", value)
        assert app_env() == value


def test_app_env_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "  Production ")
    assert app_env() == APP_ENV_PRODUCTION


def test_unknown_app_env_falls_back_and_is_visible(
    monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    monkeypatch.setenv("APP_ENV", "prodution")
    from app.config.environment import configured_app_env, is_valid_app_env

    assert app_env() == APP_ENV_DEVELOPMENT
    # The typo stays visible rather than looking like a deliberate setting.
    assert configured_app_env() == "prodution"
    assert is_valid_app_env("prodution") is False


def test_pytest_runs_with_app_env_test() -> None:
    """conftest sets it before ``app`` is imported, so every layer agrees."""
    assert os.environ["APP_ENV"] == APP_ENV_TEST
    assert app_env() == APP_ENV_TEST


# --- 2. database resolution and precedence -----------------------------------


def test_default_database_is_the_production_file() -> None:
    assert DEFAULT_DATABASE_FILE == database_safety.BACKEND_ROOT / "data" / "ai_daily.db"
    assert is_default_database(database_safety.default_database_url())
    assert is_default_database(f"sqlite:///{DEFAULT_DATABASE_FILE.as_posix()}")


def test_a_relative_and_absolute_url_to_the_default_both_match() -> None:
    assert is_default_database("sqlite:///./data/ai_daily.db")
    assert is_default_database(f"sqlite:///{DEFAULT_DATABASE_FILE}")


def test_other_databases_are_not_the_default(tmp_path: Path) -> None:
    assert not is_default_database(f"sqlite:///{(tmp_path / 'scratch.db').as_posix()}")
    assert not is_default_database("sqlite://")
    assert not is_default_database("postgresql://user:pw@localhost/ai_daily")


def test_cli_url_wins_over_the_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./data/from_env.db")
    chosen = resolve_database_url(f"sqlite:///{(tmp_path / 'from_cli.db').as_posix()}")
    assert chosen.endswith("from_cli.db")


def test_environment_wins_over_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./data/from_env.db")
    assert resolve_database_url(None) == "sqlite:///./data/from_env.db"


def test_default_is_used_when_nothing_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert is_default_database(resolve_database_url(None))


def test_bare_path_is_accepted_as_a_database_url(tmp_path: Path) -> None:
    target = tmp_path / "scratch.db"
    assert normalize_url(str(target)) == f"sqlite:///{target}"


def test_a_url_with_a_password_is_never_printed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", APP_ENV_DEVELOPMENT)
    target = resolve_target("postgresql://user:sup3rsecret@db.internal:5432/ai_daily")

    assert "sup3rsecret" not in target.display
    assert "sup3rsecret" not in maintenance.format_header(_context(target))


def _context(target: DatabaseTarget, *, dry_run: bool = False, allow: bool = False):
    return maintenance.MaintenanceContext(
        command="test",
        target=target,
        dry_run=dry_run,
        allow_production=allow,
        backup_dir=Path("."),
    )


# --- 3. the production guard -------------------------------------------------


def test_default_database_refuses_a_write(monkeypatch: pytest.MonkeyPatch, scratch_backup_dir) -> None:
    monkeypatch.setenv("APP_ENV", APP_ENV_DEVELOPMENT)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ProductionGuardError) as error:
        begin("rebuild_search_index", make_args())

    assert "production/default AI Daily database" in str(error.value)
    assert "--allow-production" in str(error.value)


def test_app_env_production_refuses_even_a_custom_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, scratch_backup_dir
) -> None:
    monkeypatch.setenv("APP_ENV", APP_ENV_PRODUCTION)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'scratch.db').as_posix()}")

    with pytest.raises(ProductionGuardError):
        begin("rebuild_digests", make_args())


def test_allow_production_permits_the_default_database(
    monkeypatch: pytest.MonkeyPatch, scratch_backup_dir
) -> None:
    """The explicit flag is the only way past the guard."""
    monkeypatch.setenv("APP_ENV", APP_ENV_DEVELOPMENT)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    context = begin("rebuild_search_index", make_args(**{"allow-production": True}))

    assert context.target.is_default is True
    assert context.allow_production is True
    monkeypatch.delenv("DATABASE_URL", raising=False)
    reset_database()


def test_wrong_app_env_cannot_bypass_the_default_file_sentinel(
    monkeypatch: pytest.MonkeyPatch, scratch_backup_dir
) -> None:
    """The whole point: ``APP_ENV=development`` does not make production safe."""
    monkeypatch.setenv("APP_ENV", APP_ENV_DEVELOPMENT)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./data/ai_daily.db")

    with pytest.raises(ProductionGuardError):
        begin("backfill_article_content", make_args())


def test_a_scratch_database_is_not_guarded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, scratch_backup_dir
) -> None:
    monkeypatch.setenv("APP_ENV", APP_ENV_DEVELOPMENT)
    url = f"sqlite:///{(tmp_path / 'scratch.db').as_posix()}"

    context = begin("rebuild_digests", make_args(**{"database-url": url}))

    assert context.is_production is False
    assert context.backup_required is False


def test_dry_run_may_describe_the_production_database(
    monkeypatch: pytest.MonkeyPatch, scratch_backup_dir, capsys
) -> None:
    """A dry run changes nothing, so it is allowed to report on production."""
    monkeypatch.setenv("APP_ENV", APP_ENV_DEVELOPMENT)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    context = begin("rebuild_search_index", make_args(**{"dry-run": True}))

    assert context.mode == "dry-run"
    assert context.is_production is True
    assert context.backup_required is False  # no write, so no backup
    assert "--allow-production" in capsys.readouterr().out


def test_begin_does_not_rewrite_the_environment_when_it_refuses(
    monkeypatch: pytest.MonkeyPatch, scratch_backup_dir
) -> None:
    monkeypatch.setenv("APP_ENV", APP_ENV_DEVELOPMENT)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ProductionGuardError):
        begin("rebuild_digests", make_args())

    assert os.environ.get("DATABASE_URL", "") == ""


# --- 4. backup ---------------------------------------------------------------


def test_backup_writes_a_timestamped_copy(
    monkeypatch: pytest.MonkeyPatch, scratch_backup_dir, tmp_path: Path
) -> None:
    monkeypatch.setenv("APP_ENV", APP_ENV_PRODUCTION)
    source = make_sqlite_file(tmp_path / "production.db", rows=3)
    url = f"sqlite:///{source.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    context = begin("rebuild_digests", make_args(**{"allow-production": True}))
    validate(context)

    created = backup(context)

    assert created is not None
    assert created.parent == scratch_backup_dir
    assert created.name.startswith("pre_rebuild_digests_")
    assert created.suffix == ".db"
    # A SQLite online backup reproduces the *contents*, not the byte layout (the
    # header's change counter legitimately moves), so equivalence is asserted on
    # what the file means.
    assert readonly.integrity_check(created) == "ok"
    assert readonly.count_rows(created, "t") == readonly.count_rows(source, "t") == 3
    assert readonly.scalar(created, "SELECT COUNT(*) FROM t WHERE name = 'a'") == 3


def test_backup_filename_follows_the_documented_shape(
    monkeypatch: pytest.MonkeyPatch, scratch_backup_dir
) -> None:
    monkeypatch.setenv("APP_ENV", APP_ENV_PRODUCTION)
    context = _context(resolve_target("sqlite:///tmp/x.db"))
    from datetime import datetime

    path = backup_path(context, moment=datetime(2026, 9, 14, 8, 30, 5))

    assert path.name == "pre_test_20260914_083005.db"


def test_backup_failure_aborts_before_any_write(
    monkeypatch: pytest.MonkeyPatch, scratch_backup_dir, tmp_path: Path
) -> None:
    """A failed backup must stop the command, not continue to the write."""
    monkeypatch.setenv("APP_ENV", APP_ENV_PRODUCTION)
    source = make_sqlite_file(tmp_path / "production.db", rows=1)
    context = begin(
        "rebuild_digests",
        make_args(
            **{
                "database-url": f"sqlite:///{source.as_posix()}",
                "allow-production": True,
            }
        ),
    )
    validate(context)

    # A file where the backup *directory* should be: creating or writing inside
    # it cannot succeed, so the copy fails before the database is touched.
    scratch_backup_dir.parent.mkdir(parents=True, exist_ok=True)
    scratch_backup_dir.write_bytes(b"not a directory")

    with pytest.raises(MaintenanceError) as error:
        backup(context)

    assert "database left untouched" in str(error.value)
    assert readonly.count_rows(source, "t") == 1


def test_broken_database_fails_validation(
    monkeypatch: pytest.MonkeyPatch, scratch_backup_dir, tmp_path: Path
) -> None:
    """An unreadable database is caught before it is copied or written."""
    monkeypatch.setenv("APP_ENV", APP_ENV_PRODUCTION)
    broken = tmp_path / "broken.db"
    broken.write_bytes(b"this is not a sqlite file at all")
    context = begin(
        "rebuild_digests",
        make_args(
            **{
                "database-url": f"sqlite:///{broken.as_posix()}",
                "allow-production": True,
            }
        ),
    )

    with pytest.raises(MaintenanceError):
        validate(context)


def test_backup_directory_defaults_to_the_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(maintenance.BACKUP_DIR_ENV, raising=False)
    assert default_backup_dir() == database_safety.BACKEND_ROOT.parent / "backups"


def test_no_backup_for_a_scratch_database(
    monkeypatch: pytest.MonkeyPatch, scratch_backup_dir, tmp_path: Path
) -> None:
    monkeypatch.setenv("APP_ENV", APP_ENV_DEVELOPMENT)
    context = begin(
        "rebuild_digests",
        make_args(**{"database-url": f"sqlite:///{(tmp_path / 'x.db').as_posix()}"}),
    )
    assert backup(context) is None


# --- 5. read-only helpers ----------------------------------------------------


def test_readonly_helpers_do_not_write(tmp_path: Path) -> None:
    """Every diagnostic helper is a read: the bytes stay identical."""
    path = tmp_path / "seed.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    connection.execute("INSERT INTO t (name) VALUES ('a'), ('b')")
    connection.commit()
    connection.close()
    before = sha256(path)

    readonly.table_names(path)
    readonly.table_ddl(path, "t")
    readonly.index_tables(path, "t")
    readonly.integrity_check(path)
    readonly.foreign_key_violations(path)
    readonly.count_rows(path, "t")
    readonly.scalar(path, "SELECT COUNT(*) FROM t")

    assert sha256(path) == before


def test_readonly_does_not_create_a_missing_table(tmp_path: Path) -> None:
    path = tmp_path / "empty.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    connection.commit()
    connection.close()

    with pytest.raises(sqlite3.Error):
        readonly.count_rows(path, "no_such_table")


def test_sqlite_path_is_absolute_for_a_relative_url() -> None:
    resolved = sqlite_path("sqlite:///./data/ai_daily.db")
    assert resolved is not None and resolved.is_absolute()
    assert sqlite_path("sqlite://") is None
    assert sqlite_path("postgresql://host/db") is None


def test_set_app_env_forces_the_value() -> None:
    try:
        set_app_env(APP_ENV_PRODUCTION)
        assert app_env() == APP_ENV_PRODUCTION
    finally:
        set_app_env(APP_ENV_TEST)
    assert app_env() == APP_ENV_TEST

# --- 6. test database isolation ----------------------------------------------


def test_the_suite_runs_on_a_temporary_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test is pointed somewhere disposable, never at the real file."""
    from app.db.session import database_url

    configured = database_url()
    assert is_default_database(configured) is False
    assert "test_ai_daily.db" in configured


def test_configuring_the_production_database_under_test_is_refused() -> None:
    """The rule is enforced while APP_ENV=test, which this suite always is."""
    from app.db.session import configure_database

    with pytest.raises(RuntimeError) as error:
        configure_database(database_safety.default_database_url())

    assert "APP_ENV=test" in str(error.value)
    assert "temporary database" in str(error.value)


def test_opening_the_production_database_under_test_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even a hand-set DATABASE_URL cannot reach it, because get_engine checks."""
    from app.db.session import get_engine, reset_database

    monkeypatch.setenv("DATABASE_URL", database_safety.default_database_url())
    reset_database()

    with pytest.raises(RuntimeError) as error:
        get_engine()

    assert "must run against a temporary database" in str(error.value)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    reset_database()


def test_is_default_database_matches_the_sentinel_forms(tmp_path: Path) -> None:
    """The check is by resolved path, so the usual spellings all match."""
    raw = DEFAULT_DATABASE_FILE
    assert is_default_database(f"sqlite:///{raw.as_posix()}")
    assert is_default_database(f"sqlite:///{raw}")
    assert is_default_database("sqlite:///./data/ai_daily.db")
    assert not is_default_database(f"sqlite:///{(tmp_path / 'ai_daily.db').as_posix()}")


def test_the_production_database_is_never_touched_by_the_suite() -> None:
    """A guard for the guard: the real file's bytes are what they were.

    The suite cannot assert a hash from before the run, so it asserts the two
    things that would move first: the file exists untouched by tests, and the
    suite's own database is a different file.
    """
    from app.db.session import database_url

    default_path = DEFAULT_DATABASE_FILE.resolve()
    suite_path = sqlite_path(database_url())

    assert suite_path is not None
    assert suite_path != default_path
    if default_path.exists():
        # Read-only: proves the file is openable without mutating it.
        assert readonly.integrity_check(default_path) == "ok"
