"""One-shot rebuild of the article search index.

The index is derived data. When it is missing (a database written before search
existed), stale (a tokenizer upgrade), or suspected wrong, this regenerates it
from ``news_articles`` alone:

* no RSS fetch, no LLM call, no article extraction;
* ``news_articles`` is only read, never written;
* digest associations are not touched;
* the index is dropped and refilled, so running it twice leaves the same state.

Usage:

    uv run python -m app.jobs.rebuild_search_index
"""

from __future__ import annotations

import argparse
import sys

from app.config.env import load_dotenv
from app.db.session import get_engine, init_db, new_session
from app.services.news_search import (
    BACKEND_LIKE,
    SearchIndexStats,
    backend_label,
    rebuild_index,
)


def rebuild() -> SearchIndexStats:
    """Rebuild the index from the stored articles, in one transaction."""
    session = new_session()
    try:
        stats = rebuild_index(session)
        session.commit()
        return stats
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rebuild the article search index")
    parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

    load_dotenv()
    init_db()
    # The fill below also has to be able to create the table, so the engine is
    # passed in rather than relying on a previous run having done it.
    print(f"Search backend: {backend_label(_backend(get_engine()))}")
    stats = rebuild()
    print()
    print("Search index rebuilt")
    print(f"Articles: {stats.articles}")
    print(f"Indexed: {stats.indexed}")
    if stats.backend == BACKEND_LIKE:
        print()
        print("FTS5 is unavailable in this Python build; search falls back to SQL LIKE.")
    return 0


def _backend(engine) -> str:
    from app.services.news_search import supported_backend

    return supported_backend(engine)


if __name__ == "__main__":
    raise SystemExit(main())
