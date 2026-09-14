"""One-shot rebuild of the article search index.

The index is derived data. When it is missing (a database written before search
existed), stale (a tokenizer upgrade), or suspected wrong, this regenerates it
from ``news_articles`` alone:

* no RSS fetch, no LLM call, no article extraction;
* ``news_articles`` is only read, never written;
* digest associations are not touched;
* the index is dropped and refilled, so running it twice leaves the same state.

This command writes the database, so it refuses to run against the production
one unless ``--allow-production`` is given, and it backs that database up first.

Usage:

    uv run python -m app.jobs.rebuild_search_index --database-url sqlite:///./data/scratch.db
    uv run python -m app.jobs.rebuild_search_index --dry-run
    uv run python -m app.jobs.rebuild_search_index --allow-production
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from app.config.env import load_dotenv
from app.config.maintenance import (
    EXIT_ABORTED,
    EXIT_REFUSED,
    MaintenanceContext,
    MaintenanceError,
    ProductionGuardError,
    add_common_arguments,
    begin,
    format_header,
    prepare_write,
)
from app.db.session import get_engine, init_db, new_session
from app.services.news_search import (
    BACKEND_LIKE,
    SearchIndexStats,
    backend_label,
    rebuild_index,
    supported_backend,
    usable_backend,
)


@dataclass(frozen=True)
class RebuildPlan:
    """What a run would do, read without changing anything."""

    backend: str
    articles: int


def plan(context: MaintenanceContext) -> RebuildPlan:
    """The work a run would do, described without changing anything."""
    from sqlalchemy import create_engine, text

    target = context.target
    if target.path is not None and not target.path.exists():
        # Nothing to read, and a dry run must not create a database file (nor its
        # schema) just to describe the work. The library's own capability is the
        # honest answer here.
        return RebuildPlan(
            backend=supported_backend(create_engine("sqlite://")), articles=0
        )

    try:
        backend = usable_backend(get_engine())
        session = new_session()
        try:
            articles = int(
                session.execute(text("SELECT COUNT(*) FROM news_articles")).scalar() or 0
            )
        finally:
            session.close()
    except Exception:
        # Describing the plan must never be the step that fails: a database that
        # is uninitialised, or not a database at all, is still reported. The
        # library's own capability is the honest answer, and ``validate`` is what
        # decides whether the command may continue.
        return RebuildPlan(
            backend=supported_backend(create_engine("sqlite://")), articles=0
        )
    return RebuildPlan(backend=backend, articles=articles)


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
    add_common_arguments(parser)
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

    load_dotenv()
    try:
        context = begin("rebuild_search_index", args)
    except ProductionGuardError as exc:
        print(str(exc))
        return EXIT_REFUSED

    planned = plan(context)
    print(format_header(context))
    print(f"Backend:     {backend_label(planned.backend)}")

    if context.dry_run:
        print()
        print("Dry run: no changes made")
        print(f"Would index: {planned.articles} articles")
        return 0

    try:
        prepare_write(context)
    except MaintenanceError as exc:
        print(f"Aborted: {exc}")
        return EXIT_ABORTED

    # The command works on its own, so the schema is made ready here rather than
    # relying on a previous API start having done it.
    init_db()
    stats = rebuild()
    print()
    print("Search index rebuilt")
    print(f"Articles: {stats.articles}")
    print(f"Indexed: {stats.indexed}")
    if stats.backend == BACKEND_LIKE:
        print()
        print("FTS5 is unavailable in this Python build; search falls back to SQL LIKE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
