"""Phase 10.10: a production write with no way to undo it must not happen.

The automatic backup covers SQLite files. A production PostgreSQL target has no
file to copy, so the honest answer is to stop rather than write un-backed-up.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config.environment import APP_ENV_PRODUCTION
from app.config.maintenance import (
    MaintenanceError,
    backup,
    begin,
    prepare_write,
    resolve_database_url,
    schema_state,
    SCHEMA_ABSENT,
    SCHEMA_PRESENT,
    SCHEMA_UNKNOWN,
    point_at,
)
from app.config.database_safety import resolve_target

POSTGRES_URL = "postgresql://user:pw@localhost:5432/ai_daily"


def make_args(**overrides):
    from app.config import maintenance

    parser = maintenance.argparse.ArgumentParser()
    maintenance.add_common_arguments(parser)
    argv = []
    for key, value in overrides.items():
        flag = f"--{key}"
        if value is True:
            argv.append(flag)
        elif value:
            argv.extend([flag, str(value)])
    return parser.parse_args(argv)


@pytest.fixture(autouse=True)
def isolated_backups(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config.maintenance import BACKUP_DIR_ENV

    monkeypatch.setenv(BACKUP_DIR_ENV, str(tmp_path / "backups"))


def test_postgresql_production_write_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("APP_ENV", APP_ENV_PRODUCTION)
    context = begin(
        "rebuild_digests",
        make_args(**{"database-url": POSTGRES_URL, "allow-production": True}),
    )

    with pytest.raises(MaintenanceError) as error:
        prepare_write(context)

    assert "unsupported" in str(error.value)
    assert "SQLite" in str(error.value)


def test_postgresql_backup_explains_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", APP_ENV_PRODUCTION)
    context = begin(
        "rebuild_search_index",
        make_args(**{"database-url": POSTGRES_URL, "allow-production": True}),
    )

    with pytest.raises(MaintenanceError):
        backup(context)


def test_a_non_production_postgresql_target_is_not_backed_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only production writes need a backup, so development is not blocked."""
    monkeypatch.setenv("APP_ENV", "development")
    context = begin(
        "rebuild_digests", make_args(**{"database-url": POSTGRES_URL})
    )

    assert context.is_production is False
    assert backup(context) is None


def test_the_postgresql_password_never_reaches_the_header(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setenv("APP_ENV", APP_ENV_PRODUCTION)
    context = begin(
        "rebuild_digests", make_args(**{"database-url": POSTGRES_URL, "allow-production": True})
    )

    from app.config.maintenance import format_header

    printed = format_header(context)
    assert "pw" not in printed.replace("localhost", "")
    assert "***" in printed

    # And the same text goes to the caller's console through ``begin``'s note.
    capsys.readouterr()


# --- schema_state -------------------------------------------------------------


def test_schema_state_on_a_missing_file(tmp_path: Path) -> None:
    assert schema_state(resolve_target(f"sqlite:///{(tmp_path / 'nope.db').as_posix()}")) == SCHEMA_ABSENT


def test_schema_state_on_a_non_sqlite_target_is_unknown() -> None:
    """Never claim a PostgreSQL database is empty: we did not look."""
    assert schema_state(resolve_target(POSTGRES_URL)) == SCHEMA_UNKNOWN


def test_schema_state_on_a_corrupt_file_is_unknown(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.db"
    path.write_bytes(b"not a database")
    assert schema_state(resolve_target(f"sqlite:///{path.as_posix()}")) == SCHEMA_UNKNOWN


def test_schema_state_on_an_initialised_database() -> None:
    from tests.test_maintenance_jobs import seed_scratch_database

    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        database = seed_scratch_database(Path(raw))
        assert schema_state(resolve_target(f"sqlite:///{database.as_posix()}")) == SCHEMA_PRESENT


# --- point_at -----------------------------------------------------------------


def test_point_at_switches_the_process_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Diagnostics must read the database they name in their header."""
    import os

    from app.db.session import database_url

    url = f"sqlite:///{(tmp_path / 'named.db').as_posix()}"
    target = point_at(url)

    assert target.display.endswith("named.db")
    assert database_url() == url
    assert os.environ["DATABASE_URL"] == url


def test_resolve_database_url_prefers_the_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./data/from_env.db")
    assert resolve_database_url("sqlite:///./data/from_cli.db").endswith("from_cli.db")
