"""Full-text search over every stored article.

Search answers one question: "where is that AI news I read before?" It covers
the whole article history, not just today's digest, and it has to keep working
on a machine whose SQLite was built without FTS5.

Backends, best first:

1. ``fts5-trigram`` - FTS5 with the trigram tokenizer. It indexes every
   three-character run, so a query is a substring search: Chinese needs no word
   segmentation and an English fragment matches mid-word. A term shorter than
   three characters cannot be expressed as a trigram (that is what a trigram
   *is*), so those terms are applied with ``LIKE`` inside the same statement.
2. ``fts5`` - FTS5 without trigram. Token search works for space-separated
   languages; Chinese does not tokenize usefully, so non-ASCII terms fall back
   to ``LIKE``.
3. ``like`` - no FTS5 at all. Everything is ``LIKE``, still executed in SQL.

The backend is detected from what SQLite actually supports rather than assumed,
and a missing FTS5 only degrades search: it can never stop the API from
starting.

Two rules this module holds to:

* Ranking here is *search* relevance (BM25, title weighted highest), which is a
  different question from the daily digest ordering in ``news_ranker``; the two
  are deliberately not shared.
* ``topic`` / ``company`` are indexed so they can be searched, but the values
  returned to the client are recomputed from the article text, exactly like the
  rest of the app, so a rule change applies to search results too.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models import NewsCategory, NewsItem
from app.services.digest_window import as_utc
from app.services.news_topics import label_article

logger = logging.getLogger(__name__)

SEARCH_TABLE = "news_search_fts"

BACKEND_TRIGRAM = "fts5-trigram"
BACKEND_FTS5 = "fts5"
BACKEND_LIKE = "like"

DEFAULT_LIMIT = 20
MAX_LIMIT = 50
# A bound on how much query text is turned into SQL, so a pasted paragraph
# cannot build an enormous statement.
MAX_TOKENS = 8
MIN_TRIGRAM_CHARS = 3
# SQLite's default SQLITE_MAX_VARIABLE_NUMBER is 999; stay well under it when
# deleting a batch of ids.
SQL_VARIABLE_CHUNK = 400

# Column order is the table definition; the BM25 weights are positional and must
# stay aligned with it. Title hits outrank summary hits, which outrank a match
# buried deep in the body, and identity-ish columns (source / company / topic)
# sit in between. ``news_id`` is UNINDEXED, so its weight is inert.
FTS_COLUMNS = (
    "news_id",
    "title_cn",
    "title_original",
    "summary",
    "why_it_matters",
    "content_original",
    "source",
    "company",
    "topic",
)
BM25_WEIGHTS = (0.0, 10.0, 10.0, 5.0, 2.0, 1.0, 3.0, 4.0, 4.0)

# The fields a query may match. ``company`` / ``topic`` exist only in the index,
# because they are derived at read time rather than stored on the article.
ARTICLE_TEXT_COLUMNS = (
    "title_cn",
    "title_original",
    "summary",
    "why_it_matters",
    "content_original",
    "source",
)
INDEX_TEXT_COLUMNS = ARTICLE_TEXT_COLUMNS + ("company", "topic")
TITLE_COLUMNS = ("title_cn", "title_original")

SNIPPET_BEFORE = 30
SNIPPET_AFTER = 70
SNIPPET_MAX = 200


@dataclass(frozen=True)
class SearchHit:
    """One search result. Deliberately carries no article body."""

    news_id: str
    title_cn: str
    original_title: str
    summary: str
    source: str
    published_at: str
    # The digest the article was published in, or None when it never reached one
    # (an article whose timestamp is still ahead of every window). Never faked.
    digest_date: str | None
    topic: str
    company: str
    snippet: str


@dataclass(frozen=True)
class SearchResults:
    query: str
    total: int
    items: list[SearchHit] = field(default_factory=list)
    backend: str = BACKEND_LIKE


@dataclass
class SearchIndexStats:
    backend: str
    articles: int = 0
    indexed: int = 0


# --- query text --------------------------------------------------------------


def query_tokens(raw: str | None) -> list[str]:
    """Split a raw query into the terms to look for, in order, deduplicated."""
    tokens: list[str] = []
    for chunk in (raw or "").split():
        token = chunk.strip()
        if not token or token in tokens:
            continue
        tokens.append(token)
        if len(tokens) >= MAX_TOKENS:
            break
    return tokens


def clamp_limit(limit: int | None) -> int:
    """The page size the API will actually use, bounded by ``MAX_LIMIT``."""
    if limit is None:
        return DEFAULT_LIMIT
    if limit < 1:
        return DEFAULT_LIMIT
    return min(limit, MAX_LIMIT)


def match_expression(tokens: list[str]) -> str:
    """An FTS5 MATCH expression for ``tokens``, ANDed together.

    Every term becomes a quoted FTS5 string literal with any inner double quote
    doubled. That is what makes punctuation safe: ``GPT-6``, ``Anthropic's``,
    ``a:b``, ``(x)`` and a bare ``"`` are all text to FTS5 rather than syntax, so
    no user input can produce a malformed MATCH or a 500.
    """
    return " AND ".join('"' + token.replace('"', '""') + '"' for token in tokens)


def _like_pattern(token: str) -> str:
    """A LIKE pattern for a literal term, with LIKE's own wildcards escaped."""
    escaped = token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _is_ascii(token: str) -> bool:
    return all(ord(char) < 128 for char in token)


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _iso_timestamp(value) -> str:
    """A stored timestamp as an ISO-8601 UTC string, or an empty string.

    The same shape the digest endpoints emit, whatever form the column came
    back in: an aware ``datetime`` is converted to UTC, a naive one is read as
    UTC (matching how timestamps are stored), and SQLite's own text format is
    parsed rather than passed through.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return ""
        try:
            value = datetime.fromisoformat(cleaned)
        except ValueError:
            return cleaned
    return as_utc(value).isoformat()


# --- snippet -----------------------------------------------------------------


def matches_text(value: str | None, tokens: list[str]) -> bool:
    """True when any term occurs in the text, case-insensitively."""
    lowered = (value or "").lower()
    return any(token.lower() in lowered for token in tokens)


def choose_snippet(summary: str, body: str, title: str, tokens: list[str]) -> str:
    """The excerpt to show for a hit.

    The first candidate that actually contains a term wins, preferring the
    summary because it is the shortest text that still reads as a sentence and
    the body when the match is only there. A candidate without the term is
    skipped, so the excerpt is centred on what was searched for instead of
    quoting the start of an unrelated paragraph.
    """
    candidates = [candidate for candidate in (summary, body, title) if candidate]
    for candidate in candidates:
        if matches_text(candidate, tokens):
            return build_snippet(candidate, tokens)
    # Nothing contained a term (a hit from a column not shown here): still give
    # the reader context rather than an empty row.
    return build_snippet(candidates[0], tokens) if candidates else ""


def build_snippet(
    text: str | None,
    tokens: list[str],
    *,
    before: int = SNIPPET_BEFORE,
    after: int = SNIPPET_AFTER,
    max_length: int = SNIPPET_MAX,
) -> str:
    """A short excerpt of ``text`` centred on the first term it contains.

    Sanitised to plain text (whitespace collapsed, no markup), because the source
    is stored cleaned text and the client renders it as a string. When no term is
    found the head of the text is used, so a hit from another column still has
    context. Slicing is by code point, so it can never split a character.
    """
    flat = " ".join((text or "").split())
    if not flat:
        return ""

    lowered = flat.lower()
    hit_at = -1
    hit_length = 0
    for token in tokens:
        position = lowered.find(token.lower())
        if position != -1 and (hit_at == -1 or position < hit_at):
            hit_at = position
            hit_length = len(token)

    if hit_at == -1:
        head = flat[:max_length].rstrip()
        return head + ("…" if len(flat) > len(head) else "")

    start = max(0, hit_at - before)
    end = min(len(flat), hit_at + hit_length + after)
    excerpt = flat[start:end].strip()
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(flat) else ""
    return f"{prefix}{excerpt}{suffix}"


# --- backend detection -------------------------------------------------------


def _dialect(session: Session) -> str:
    return session.get_bind().dialect.name


def existing_backend(session: Session) -> str | None:
    """The backend the index on this database was built with, if it exists."""
    if _dialect(session) != "sqlite":
        return None
    ddl = session.execute(
        text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = :name"),
        {"name": SEARCH_TABLE},
    ).scalar()
    if not ddl:
        return None
    lowered = ddl.lower()
    if "fts5" not in lowered:
        return None
    return BACKEND_TRIGRAM if "trigram" in lowered else BACKEND_FTS5


def search_backend(session: Session) -> str:
    """The backend to search with right now."""
    return existing_backend(session) or BACKEND_LIKE


def supported_backend(engine: Engine) -> str:
    """The best backend the SQLite in this process can actually build.

    Purely a capability question, so it is answered against an in-memory
    database: whether the linked SQLite knows FTS5 and a tokenizer is a property
    of the library, not of any particular file. Asking this way means a
    read-only diagnostic can call it too - nothing is created on disk, and a
    tokenizer the library does not know about simply fails here.
    """
    if engine.dialect.name != "sqlite":
        return BACKEND_LIKE
    for backend, tokenizer in ((BACKEND_TRIGRAM, "trigram"), (BACKEND_FTS5, "unicode61")):
        if _library_supports(tokenizer):
            return backend
    return BACKEND_LIKE


@lru_cache(maxsize=None)
def _library_supports(tokenizer: str) -> bool:
    """Whether FTS5 can be built with ``tokenizer`` by the linked SQLite."""
    import sqlite3

    connection = sqlite3.connect(":memory:")
    try:
        connection.execute(
            f'CREATE VIRTUAL TABLE probe USING fts5(x, tokenize=\'{tokenizer}\')'
        )
        return True
    except sqlite3.Error:
        logger.debug("fts5 %s tokenizer unavailable", tokenizer, exc_info=True)
        return False
    finally:
        connection.close()


def existing_index_backend(engine: Engine) -> str | None:
    """The backend the index already in this database was created with.

    A read: it looks the table up in ``sqlite_master`` and reads nothing else.
    Returns None when the database has no FTS index at all.
    """
    if engine.dialect.name != "sqlite":
        return None
    with engine.connect() as connection:
        ddl = connection.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            (SEARCH_TABLE,),
        ).scalar()
    if not ddl:
        return None
    lowered = str(ddl).lower()
    if "fts5" not in lowered:
        return None
    return BACKEND_TRIGRAM if "trigram" in lowered else BACKEND_FTS5


def usable_backend(engine: Engine) -> str:
    """The backend a caller may search with right now.

    Prefers the index that exists, because that is what a query would hit; falls
    back to what could be built. Used by diagnostics, which must not create
    anything and must still report the truth about an unindexed database.
    """
    return existing_index_backend(engine) or supported_backend(engine)


def backend_label(backend: str) -> str:
    if backend == BACKEND_TRIGRAM:
        return "FTS5 (trigram)"
    if backend == BACKEND_FTS5:
        return "FTS5 (unicode61)"
    return "LIKE fallback"


def _create_statement(backend: str) -> str:
    tokenizer = "trigram" if backend == BACKEND_TRIGRAM else "unicode61"
    columns = ", ".join(
        f'"{column}"' if column != "news_id" else '"news_id" UNINDEXED'
        for column in FTS_COLUMNS
    )
    return (
        f'CREATE VIRTUAL TABLE IF NOT EXISTS "{SEARCH_TABLE}" '
        f"USING fts5({columns}, tokenize='{tokenizer}')"
    )


def ensure_table(engine: Engine) -> tuple[str, bool]:
    """Create the index with the best available backend, or upgrade it.

    Returns ``(backend, recreated)``. A table built with a weaker tokenizer than
    the library now supports (an older Python, a moved database file) is replaced
    so search actually gets the better tokenizer; the caller is told a rebuild is
    required. A missing FTS5 leaves any existing table alone rather than dropping
    data it cannot use.
    """
    desired = supported_backend(engine)
    if desired == BACKEND_LIKE:
        return BACKEND_LIKE, False

    if engine.dialect.name == "sqlite":
        current = existing_index_backend(engine)
        if current == desired:
            return desired, False
        with engine.begin() as connection:
            if current is not None:
                connection.exec_driver_sql(f'DROP TABLE IF EXISTS "{SEARCH_TABLE}"')
            connection.exec_driver_sql(_create_statement(desired))
        return desired, True
    return desired, False


# --- index writes ------------------------------------------------------------


def _insert_statement() -> str:
    columns = ", ".join(f'"{column}"' for column in FTS_COLUMNS)
    placeholders = ", ".join("?" for _ in FTS_COLUMNS)
    return f'INSERT INTO "{SEARCH_TABLE}" ({columns}) VALUES ({placeholders})'


def _index_values(item: NewsItem) -> tuple:
    """The indexed row for one article, with its current topic and company."""
    topic, company = label_article(item)
    return (
        item.id,
        item.title_cn or "",
        item.title_original or "",
        item.summary or "",
        item.why_it_matters or "",
        item.content_original or "",
        item.source or "",
        company,
        topic,
    )


def index_items(session: Session, items: list[NewsItem]) -> int:
    """Bring the index up to date for ``items``, in the caller's transaction.

    Replace-by-id rather than insert: an article whose body was extracted later,
    or whose Chinese summary was re-generated, must update its index row instead
    of accumulating a second one. No-op when there is no FTS index to write.
    """
    if not items or search_backend(session) == BACKEND_LIKE:
        return 0

    unique: dict[str, NewsItem] = {}
    for item in items:
        unique[item.id] = item

    connection = session.connection()
    for chunk in _chunks(list(unique), SQL_VARIABLE_CHUNK):
        placeholders = ", ".join("?" for _ in chunk)
        connection.exec_driver_sql(
            f'DELETE FROM "{SEARCH_TABLE}" WHERE news_id IN ({placeholders})', tuple(chunk)
        )
    connection.exec_driver_sql(_insert_statement(), [_index_values(item) for item in unique.values()])
    return len(unique)


def reindex_all(session: Session, items: list[NewsItem]) -> int:
    """Rebuild the whole index from ``items``, in the caller's transaction."""
    if search_backend(session) == BACKEND_LIKE:
        return 0
    connection = session.connection()
    connection.exec_driver_sql(f'DELETE FROM "{SEARCH_TABLE}"')
    unique: dict[str, NewsItem] = {item.id: item for item in items}
    if unique:
        connection.exec_driver_sql(
            _insert_statement(), [_index_values(item) for item in unique.values()]
        )
    return len(unique)


def _stored_articles(session: Session) -> list[NewsItem]:
    """Every stored article as a ``NewsItem`` the labeller understands.

    Columns are read by name, not by position: a positional mapping silently
    swaps fields when the select list changes, and swapping ``source`` with the
    body would quietly index the wrong text.
    """
    statement = text(
        "SELECT id, title_cn, title_original, summary, why_it_matters, "
        "content_original, source FROM news_articles"
    )
    rows = session.execute(statement).mappings().all()
    return [
        NewsItem(
            id=row["id"],
            title_cn=row["title_cn"] or "",
            title_original=row["title_original"] or "",
            summary=row["summary"] or "",
            why_it_matters=row["why_it_matters"] or "",
            source=row["source"] or "",
            source_type="",
            published_at="",
            category=NewsCategory.highlight,
            tags=[],
            url="",
            content_original=row["content_original"] or "",
        )
        for row in rows
    ]


def rebuild_index(session: Session) -> SearchIndexStats:
    """Drop the index contents and rebuild them from ``news_articles``.

    Idempotent: it reads only the article table and writes only the index, so it
    touches no digest association, calls no RSS feed and no LLM, and can be run
    as often as needed.
    """
    # Create the table when it is missing so the command works on its own, not
    # only after the API has started once.
    backend, _recreated = ensure_table(session.get_bind())
    stats = SearchIndexStats(backend=backend)
    if backend == BACKEND_LIKE:
        return stats
    articles = _stored_articles(session)
    stats.articles = len(articles)
    stats.indexed = reindex_all(session, articles)
    return stats


def ensure_index(engine: Engine) -> SearchIndexStats:
    """Create or upgrade the index and index existing articles when needed.

    Called at startup so search works on a database written before this phase:
    the index is created if missing and filled if empty, without the user having
    to delete or recreate anything.
    """
    backend, recreated = ensure_table(engine)
    stats = SearchIndexStats(backend=backend)
    if backend == BACKEND_LIKE:
        return stats

    from app.db.session import new_session

    session = new_session()
    try:
        if recreated or _index_is_empty(session):
            stats = rebuild_index(session)
            session.commit()
        else:
            stats.articles = _article_count(session)
            stats.indexed = _index_count(session)
        return stats
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _index_count(session: Session) -> int:
    return int(
        session.execute(text(f'SELECT COUNT(*) FROM "{SEARCH_TABLE}"')).scalar() or 0
    )


def _article_count(session: Session) -> int:
    return int(session.execute(text("SELECT COUNT(*) FROM news_articles")).scalar() or 0)


def _index_is_empty(session: Session) -> bool:
    return _index_count(session) == 0 and _article_count(session) > 0


# --- query -------------------------------------------------------------------


def _like_predicate(
    columns: tuple[str, ...], prefix: str, tokens: list[str], *, qualifier: str
) -> tuple[str, dict]:
    """``(col LIKE :p OR ...) AND (...)`` over ``tokens``, with its parameters.

    ``qualifier`` is the table (or alias) the columns belong to. It is always
    supplied because both backends join two relations that share column names,
    and an unqualified name would be ambiguous.
    """
    params: dict[str, str] = {}
    per_token: list[str] = []
    for index, token in enumerate(tokens):
        name = f"{prefix}{index}"
        params[name] = _like_pattern(token)
        comparisons = " OR ".join(
            f'{qualifier}."{column}" LIKE :{name} ESCAPE \'\\\'' for column in columns
        )
        per_token.append(f"({comparisons})")
    return " AND ".join(per_token), params


def _title_predicate(tokens: list[str], prefix: str, *, qualifier: str) -> tuple[str, dict]:
    """A weaker "did the title match" test, for ordering without BM25."""
    params: dict[str, str] = {}
    parts: list[str] = []
    for index, token in enumerate(tokens):
        name = f"{prefix}{index}"
        params[name] = _like_pattern(token)
        comparisons = " OR ".join(
            f'{qualifier}."{column}" LIKE :{name} ESCAPE \'\\\'' for column in TITLE_COLUMNS
        )
        parts.append(f"({comparisons})")
    return " OR ".join(parts), params


def _fts_tokens(backend: str, tokens: list[str]) -> tuple[list[str], list[str]]:
    """Split terms into the ones FTS can match and the ones ``LIKE`` must handle.

    A term is only dropped from FTS, never discarded: whatever the tokenizer
    cannot index still has to be applied, or a short query would silently match
    everything instead of narrowing the result.
    """
    if backend == BACKEND_TRIGRAM:
        fts = [token for token in tokens if len(token) >= MIN_TRIGRAM_CHARS]
        return fts, [token for token in tokens if token not in fts]
    if backend == BACKEND_FTS5:
        fts = [token for token in tokens if _is_ascii(token)]
        return fts, [token for token in tokens if token not in fts]
    return [], list(tokens)


_SELECT_FIELDS = (
    "n.id, n.title_cn, n.title_original, n.summary, n.why_it_matters, "
    "n.source, n.published_at, n.content_original, "
    "(SELECT MIN(dd.digest_date) FROM daily_digest_news dd WHERE dd.news_id = n.id) AS digest_date"
)


def _row_to_hit(row, tokens: list[str]) -> SearchHit:
    """One result row as a hit, with its labels recomputed from the article."""
    # Normalise the stored timestamp the same way the digest reads do, so a
    # client sees one format everywhere. A raw SQL read of a DATETIME column
    # comes back as SQLite's own "YYYY-MM-DD HH:MM:SS.ffffff" text, which is not
    # what the rest of the API returns and not ISO-8601.
    published = _iso_timestamp(row["published_at"])
    item = NewsItem(
        id=row["id"],
        title_cn=row["title_cn"] or "",
        title_original=row["title_original"] or "",
        summary=row["summary"] or "",
        why_it_matters=row["why_it_matters"] or "",
        source=row["source"] or "",
        source_type="",
        published_at=published,
        category=NewsCategory.highlight,
        tags=[],
        url="",
    )
    # Recomputed, not read back from the index: the labels stay a pure function
    # of the article text, so a rule change applies to old results immediately.
    topic, company = label_article(item)
    return SearchHit(
        news_id=row["id"],
        title_cn=item.title_cn,
        original_title=item.title_original,
        summary=item.summary,
        source=item.source,
        published_at=item.published_at,
        digest_date=row["digest_date"],
        topic=topic,
        company=company,
        snippet=choose_snippet(
            item.summary, row["content_original"] or "", item.title_cn or item.title_original, tokens
        ),
    )


def search_articles(
    session: Session,
    raw_query: str | None,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> SearchResults:
    """Search the whole archive, most relevant first.

    Relevance comes from BM25 with the title weighted highest, and publication
    time is only a tie-breaker. ``importance_score`` is not consulted: a search
    result's job is to be about what was asked for, not to re-run the daily
    ranking.
    """
    query = (raw_query or "").strip()
    tokens = query_tokens(query)
    backend = search_backend(session)
    if not tokens:
        return SearchResults(query=query, total=0, items=[], backend=backend)

    resolved_limit = clamp_limit(limit)
    resolved_offset = max(0, offset)
    fts_tokens, extra_like = _fts_tokens(backend, tokens)
    params: dict[str, object] = {}
    where: list[str] = []

    if backend == BACKEND_LIKE:
        # No index to consult: the LIKE term list carries the whole query.
        predicates, like_params = _like_predicate(ARTICLE_TEXT_COLUMNS, "l", tokens, qualifier="n")
        params.update(like_params)
        where.append(predicates)
        title_expr, title_params = _title_predicate(tokens, "t", qualifier="n")
        params.update(title_params)
        order = f"CASE WHEN {title_expr} THEN 0 ELSE 1 END ASC, n.published_at DESC"
        source = "news_articles n"
    else:
        source = f'"{SEARCH_TABLE}" JOIN news_articles n ON n.id = "{SEARCH_TABLE}".news_id'
        if fts_tokens:
            params["match"] = match_expression(fts_tokens)
            where.append(f'"{SEARCH_TABLE}" MATCH :match')
        if extra_like:
            # Applied to the index's own copy of the columns; the weight of the
            # match still comes from BM25 over the FTS terms.
            predicates, like_params = _like_predicate(
                INDEX_TEXT_COLUMNS, "l", extra_like, qualifier=f'"{SEARCH_TABLE}"'
            )
            params.update(like_params)
            where.append(predicates)
        if fts_tokens:
            weights = ", ".join(str(weight) for weight in BM25_WEIGHTS)
            order = f"bm25(\"{SEARCH_TABLE}\", {weights}) ASC, n.published_at DESC"
        else:
            # Every term was too short for the tokenizer, so there is nothing to
            # score with BM25; fall back to "did the title match" plus recency.
            title_expr, title_params = _title_predicate(tokens, "t", qualifier="n")
            params.update(title_params)
            order = f"CASE WHEN {title_expr} THEN 0 ELSE 1 END ASC, n.published_at DESC"

    where_sql = " AND ".join(where) if where else "1"
    total = int(
        session.execute(
            text(f"SELECT COUNT(*) FROM {source} WHERE {where_sql}"), params
        ).scalar()
        or 0
    )
    rows = (
        session.execute(
            text(
                f"SELECT {_SELECT_FIELDS} FROM {source} WHERE {where_sql} "
                f"ORDER BY {order} LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": resolved_limit, "offset": resolved_offset},
        )
        .mappings()
        .all()
    )

    return SearchResults(
        query=query,
        total=total,
        items=[_row_to_hit(row, tokens) for row in rows],
        backend=backend,
    )
