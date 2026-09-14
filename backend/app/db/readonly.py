"""Read-only access to a SQLite file, for diagnostics.

Diagnostics exist to tell the truth about a database, so they must not change
it: every helper here opens ``mode=ro`` and issues only PRAGMAs and SELECTs.
There is no ``create_all``, no schema upgrade, no index creation, no VACUUM and
no write of any kind.
"""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

# Files are small enough that hashing in chunks keeps memory flat without
# slowing the scan down.
HASH_CHUNK = 1024 * 1024


@contextmanager
def read_only_connection(path: Path) -> Iterator[sqlite3.Connection]:
    """Open ``path`` read-only. Raises ``sqlite3.Error`` if it cannot be read."""
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        yield connection
    finally:
        connection.close()


def table_names(path: Path) -> set[str]:
    """Every table and virtual table in the file, read without creating any."""
    with read_only_connection(path) as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    return {str(row[0]) for row in rows}


def table_ddl(path: Path, name: str) -> str | None:
    """The stored DDL of one table, so a caller can classify it."""
    with read_only_connection(path) as connection:
        row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
        ).fetchone()
    return None if row is None or row[0] is None else str(row[0])


def index_tables(path: Path, prefix: str) -> list[str]:
    """Table names starting with ``prefix``, sorted, without altering anything."""
    return sorted(name for name in table_names(path) if name.startswith(prefix))


def integrity_check(path: Path) -> str:
    """SQLite's own integrity verdict for the file (``ok`` when healthy)."""
    with read_only_connection(path) as connection:
        row = connection.execute("PRAGMA integrity_check").fetchone()
    return str(row[0]) if row else "no result"


def foreign_key_violations(path: Path) -> list[tuple]:
    """Rows that violate a declared foreign key. Empty means the schema holds."""
    with read_only_connection(path) as connection:
        return connection.execute("PRAGMA foreign_key_check").fetchall()


def count_rows(path: Path, table: str) -> int:
    """Row count of ``table``. The caller decides whether it exists."""
    with read_only_connection(path) as connection:
        row = connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
    return int(row[0]) if row else 0


def scalar(path: Path, sql: str) -> object:
    """Run one read-only statement and return its first column."""
    with read_only_connection(path) as connection:
        row = connection.execute(sql).fetchone()
    return None if row is None else row[0]


def file_sha256(path: Path) -> str:
    """The file's SHA256, so a caller can prove a command changed nothing."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def human_size(size: int) -> str:
    """A short, human-readable size (``12.3 KB``)."""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} GB"
