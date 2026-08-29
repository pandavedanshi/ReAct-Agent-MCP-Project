"""Layer 1 of the read-only boundary: static analysis of LLM-generated SQL.

A language model will occasionally emit a destructive statement -- because the user
asked for one, because a prompt-injected row told it to, or simply because it
hallucinated. This module rejects such statements *before* they reach the database.

It is deliberately an allowlist: only a single, self-contained SELECT survives.
Layers 2 (sqlite3 authorizer) and 3 (read-only connection URI) live in database.py
and would independently stop anything that slipped through here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import sqlglot
from sqlglot import exp

# Statement types that may appear as the root of an accepted query.
ALLOWED_ROOTS = (exp.Select, exp.Union, exp.Except, exp.Intersect, exp.Subquery)

# Any of these anywhere in the parse tree is an immediate rejection. Covers DML,
# DDL, transaction control, and SQLite-specific escapes such as ATTACH.
FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter,
    exp.TruncateTable, exp.Merge, exp.Attach, exp.Detach, exp.Pragma, exp.Set,
    exp.Transaction, exp.Commit, exp.Rollback, exp.Grant, exp.Copy, exp.Use,
    exp.Command,  # sqlglot's catch-all for unparsed verbs like VACUUM / REINDEX
)

# SQLite functions that touch the filesystem or mutate engine state. None of them
# are needed to answer a question about university records.
FORBIDDEN_FUNCTIONS = {
    "load_extension", "readfile", "writefile", "edit", "fts3_tokenizer",
    "sqlite_compileoption_used", "sqlite_compileoption_get",
}

# Final regex backstop against constructs a parser might normalise away.
FORBIDDEN_PATTERNS = [
    (re.compile(r"\bATTACH\b", re.I), "ATTACH is not permitted"),
    (re.compile(r"\bPRAGMA\b", re.I), "PRAGMA is not permitted"),
    (re.compile(r"\bVACUUM\b", re.I), "VACUUM is not permitted"),
    (re.compile(r"\bsqlite_(master|schema|temp_master)\b", re.I),
     "query the schema through describe_table/get_database_schema, not sqlite internals"),
]

MAX_SQL_LENGTH = 8_000


class UnsafeQueryError(Exception):
    """Raised when a statement violates the read-only contract."""


@dataclass(frozen=True)
class GuardReport:
    """Outcome of validation, returned so callers can log what was checked."""

    sql: str            # the statement, stripped of trailing semicolons
    root_type: str      # e.g. "Select" / "Union"
    tables: tuple       # table names referenced, for audit logging
    has_limit: bool


def _referenced_tables(tree: exp.Expression) -> tuple:
    names = {t.name for t in tree.find_all(exp.Table) if t.name}
    return tuple(sorted(names))


def validate(sql: str) -> GuardReport:
    """Validate `sql` and return a report, or raise UnsafeQueryError.

    Rejects on: empty input, oversized input, multiple statements, a non-SELECT
    root, any forbidden node in the tree, filesystem functions, or a pattern match.
    """
    if not sql or not sql.strip():
        raise UnsafeQueryError("Empty query.")

    sql = sql.strip().rstrip(";").strip()

    if len(sql) > MAX_SQL_LENGTH:
        raise UnsafeQueryError(f"Query exceeds {MAX_SQL_LENGTH} characters.")

    for pattern, message in FORBIDDEN_PATTERNS:
        if pattern.search(sql):
            raise UnsafeQueryError(message)

    try:
        statements = sqlglot.parse(sql, dialect="sqlite")
    except Exception as exc:
        raise UnsafeQueryError(f"Could not parse SQL: {exc}") from exc

    statements = [s for s in statements if s is not None]
    if len(statements) == 0:
        raise UnsafeQueryError("No statement found.")
    # Stacked statements are the classic injection vector: "SELECT 1; DELETE FROM x".
    if len(statements) > 1:
        raise UnsafeQueryError(
            f"Only one statement per call is allowed ({len(statements)} were supplied)."
        )

    tree = statements[0]

    # A CTE is fine as long as the statement it feeds is a SELECT.
    root = tree.this if isinstance(tree, exp.With) else tree
    if not isinstance(root, ALLOWED_ROOTS):
        raise UnsafeQueryError(
            f"Only SELECT queries are permitted; received {type(root).__name__.upper()}."
        )

    for node in tree.walk():
        if isinstance(node, FORBIDDEN_NODES):
            raise UnsafeQueryError(
                f"Statement contains a forbidden operation: {type(node).__name__.upper()}."
            )
        if isinstance(node, exp.Anonymous):
            fn = (node.name or "").lower()
            if fn in FORBIDDEN_FUNCTIONS:
                raise UnsafeQueryError(f"Function {fn}() is not permitted.")

    return GuardReport(
        sql=sql,
        root_type=type(root).__name__,
        tables=_referenced_tables(tree),
        has_limit=bool(tree.find(exp.Limit)),
    )


def apply_row_limit(sql: str, max_rows: int) -> str:
    """Append a LIMIT when the query has none, so one bad query cannot stream
    the whole table back into the model's context window."""
    tree = sqlglot.parse_one(sql, dialect="sqlite")
    if tree.find(exp.Limit) is not None:
        return sql
    return tree.limit(max_rows).sql(dialect="sqlite")
