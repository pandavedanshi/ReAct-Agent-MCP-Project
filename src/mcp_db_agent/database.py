"""Data-access layer. Owns the only code in the project that touches SQLite.

Three independent controls enforce the read-only boundary:

  Layer 1  guard.validate()          static SQL analysis (guard.py)
  Layer 2  sqlite3 set_authorizer()  per-operation veto inside the engine
  Layer 3  file:...?mode=ro URI      the driver opens the file read-only

Layer 1 produces good error messages the agent can recover from. Layers 2 and 3
are the ones that actually make a write impossible, and they hold even if the
guard is bypassed or buggy.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import settings
from .guard import GuardReport, UnsafeQueryError, apply_row_limit, validate

# Authorizer actions compatible with a read-only session. Anything absent from
# this set is denied, which is why new SQLite verbs fail closed rather than open.
_ALLOWED_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    sqlite3.SQLITE_RECURSIVE,
}


def _authorizer(action: int, arg1, arg2, db_name, trigger) -> int:
    """Called by SQLite for every operation a prepared statement attempts."""
    if action not in _ALLOWED_ACTIONS:
        return sqlite3.SQLITE_DENY
    # SQLITE_READ on an internal table would let the model read the raw schema
    # blob; the describe_table tool exposes that in a controlled form instead.
    if action == sqlite3.SQLITE_READ and isinstance(arg1, str) and arg1.startswith("sqlite_"):
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


class QueryTimeout(Exception):
    """Raised when a query exceeds settings.query_timeout_ms."""


@dataclass
class QueryResult:
    """Everything the MCP layer needs to describe one executed query."""

    sql: str
    columns: list
    rows: list
    row_count: int
    execution_ms: float
    truncated: bool
    plan: list = field(default_factory=list)
    used_index: bool = False
    full_scans: list = field(default_factory=list)


# In-memory audit trail. Every executed query lands here so the get_query_log
# tool can show latency and index usage across a whole agent session.
QUERY_LOG: list = []


def database_path() -> Path:
    path = settings.database_path
    if not path.exists():
        raise FileNotFoundError(
            f"Database not found at {path}. Run: python scripts/init_db.py"
        )
    return path


def connect() -> sqlite3.Connection:
    """Open a hardened read-only connection (layers 2 and 3)."""
    uri = f"file:{database_path().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.set_authorizer(_authorizer)
    return conn


def _install_timeout(conn: sqlite3.Connection, timeout_ms: int) -> None:
    """Abort long-running queries.

    SQLite calls the progress handler every N virtual-machine instructions; a
    non-zero return interrupts the statement. This bounds a runaway cartesian
    join that the model might generate by mistake.
    """
    deadline = time.perf_counter() + timeout_ms / 1000.0

    def _tick() -> int:
        return 1 if time.perf_counter() > deadline else 0

    conn.set_progress_handler(_tick, 10_000)


def _analyse_plan(conn: sqlite3.Connection, sql: str) -> tuple:
    """Return (plan_lines, used_index, full_scans) from EXPLAIN QUERY PLAN.

    SQLite reports 'SEARCH <table> USING INDEX <name>' when an index drives the
    lookup and 'SCAN <table>' when it walks every row. Surfacing the difference
    is what lets the agent notice it wrote a query the optimiser cannot help.
    """
    plan_rows = conn.execute(f"EXPLAIN QUERY PLAN {sql}").fetchall()
    lines = [row["detail"] for row in plan_rows]
    used_index = any("USING INDEX" in ln or "USING COVERING INDEX" in ln for ln in lines)
    # A SCAN of a tiny lookup table is fine; only flag scans SQLite did not index.
    full_scans = [ln for ln in lines if ln.startswith("SCAN") and "USING" not in ln]
    return lines, used_index, full_scans


def run_select(sql: str, max_rows: int | None = None) -> QueryResult:
    """Validate, plan, time, and execute a single SELECT.

    Raises UnsafeQueryError for anything that is not a read, QueryTimeout if it
    runs too long, and sqlite3.Error for genuine SQL mistakes (which the agent
    is expected to read and correct on its next turn).
    """
    max_rows = max_rows or settings.max_rows
    report: GuardReport = validate(sql)
    # Fetch one row beyond the cap: if it comes back, the result set was larger
    # than max_rows and the caller needs to be told the output is incomplete.
    safe_sql = apply_row_limit(report.sql, max_rows + 1)

    conn = connect()
    try:
        plan, used_index, full_scans = _analyse_plan(conn, safe_sql)

        _install_timeout(conn, settings.query_timeout_ms)
        started = time.perf_counter()
        try:
            cursor = conn.execute(safe_sql)
            rows = cursor.fetchmany(max_rows + 1)
        except sqlite3.OperationalError as exc:
            if "interrupted" in str(exc).lower():
                raise QueryTimeout(
                    f"Query exceeded {settings.query_timeout_ms} ms and was cancelled."
                ) from exc
            raise
        finally:
            conn.set_progress_handler(None, 0)
        elapsed_ms = (time.perf_counter() - started) * 1000

        truncated = len(rows) > max_rows
        rows = rows[:max_rows]
        columns = [d[0] for d in cursor.description] if cursor.description else []

        result = QueryResult(
            sql=safe_sql,
            columns=columns,
            rows=[dict(r) for r in rows],
            row_count=len(rows),
            execution_ms=round(elapsed_ms, 3),
            truncated=truncated,
            plan=plan,
            used_index=used_index,
            full_scans=full_scans,
        )
        QUERY_LOG.append({
            "sql": safe_sql,
            "tables": list(report.tables),
            "rows": result.row_count,
            "execution_ms": result.execution_ms,
            "used_index": used_index,
            "full_scans": len(full_scans),
        })
        return result
    finally:
        conn.close()


def explain(sql: str) -> dict:
    """Return the query plan without executing the statement."""
    report = validate(sql)
    conn = connect()
    try:
        plan, used_index, full_scans = _analyse_plan(conn, report.sql)
    finally:
        conn.close()
    return {
        "sql": report.sql,
        "plan": plan,
        "used_index": used_index,
        "full_table_scans": full_scans,
        "advice": (
            "Plan uses at least one index."
            if used_index and not full_scans
            else "This query walks whole tables. Filter or join on an indexed column "
                 "(any *_id foreign key, students.enrollment_year, enrollments.grade)."
        ),
    }


def list_tables() -> list:
    """Table names plus row counts, read from the catalogue.

    Uses a separate plain connection because the authorizer blocks sqlite_master
    on the hardened one -- the catalogue read is trusted server code, not
    model-supplied SQL.
    """
    conn = sqlite3.connect(f"file:{database_path().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        names = [r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return [{"table": n,
                 "row_count": conn.execute(f"SELECT COUNT(*) FROM {n}").fetchone()[0]}
                for n in names]
    finally:
        conn.close()


def describe(table: str) -> dict:
    """Columns, primary key, foreign keys and indexes for one table."""
    tables = {t["table"] for t in list_tables()}
    if table not in tables:
        raise ValueError(f"Unknown table '{table}'. Available: {sorted(tables)}")

    conn = sqlite3.connect(f"file:{database_path().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        columns = [
            {
                "name": r["name"],
                "type": r["type"],
                "not_null": bool(r["notnull"]),
                "default": r["dflt_value"],
                "primary_key": bool(r["pk"]),
            }
            for r in conn.execute(f"PRAGMA table_info({table})")
        ]
        foreign_keys = [
            {"column": r["from"], "references": f"{r['table']}.{r['to']}"}
            for r in conn.execute(f"PRAGMA foreign_key_list({table})")
        ]
        indexes = []
        for r in conn.execute(f"PRAGMA index_list({table})"):
            cols = [c["name"] for c in conn.execute(f"PRAGMA index_info({r['name']})")]
            indexes.append({"name": r["name"], "columns": cols, "unique": bool(r["unique"])})
        ddl = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()[0]
        row_count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()

    return {
        "table": table,
        "row_count": row_count,
        "columns": columns,
        "foreign_keys": foreign_keys,
        "indexes": indexes,
        "ddl": ddl,
    }


def full_schema() -> dict:
    """Whole-database schema plus the FK edge list.

    The agent fetches this once per session and keeps it in context; the edge
    list is what lets it construct multi-hop JOINs without trial and error.
    """
    tables = [describe(t["table"]) for t in list_tables()]
    edges = [
        {"from": t["table"], "column": fk["column"], "to": fk["references"]}
        for t in tables for fk in t["foreign_keys"]
    ]
    return {
        "database": database_path().name,
        "tables": tables,
        "relationships": edges,
        "note": "Read-only. Only SELECT statements are accepted by run_select_query.",
    }


def sample_rows(table: str, limit: int = 5) -> dict:
    """A few real rows so the model can see actual value formats.

    Prevents a common failure mode: filtering on WHERE grade = 'A+' when the
    column only ever contains 'A', or on status = 'Active' instead of 'active'.
    """
    describe(table)  # validates the table name before interpolation
    limit = max(1, min(int(limit), 20))
    conn = connect()
    try:
        rows = [dict(r) for r in conn.execute(f"SELECT * FROM {table} LIMIT {limit}")]
    finally:
        conn.close()
    return {"table": table, "sample": rows}


def query_log(limit: int = 20) -> dict:
    """Recent executed queries with timing and index usage."""
    recent = QUERY_LOG[-limit:]
    total_ms = sum(q["execution_ms"] for q in recent)
    return {
        "queries": recent,
        "count": len(recent),
        "total_execution_ms": round(total_ms, 3),
        "scans_without_index": sum(1 for q in recent if not q["used_index"]),
    }


__all__ = [
    "QueryResult", "QueryTimeout", "UnsafeQueryError", "connect", "describe",
    "explain", "full_schema", "list_tables", "query_log", "run_select",
    "sample_rows",
]
