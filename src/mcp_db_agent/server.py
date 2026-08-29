"""FastMCP server: exposes the database as MCP tools.

This process is the only one that ever opens the database. The agent — and the
LLM behind it — reaches the data solely through the tool calls declared here, so
no database path or credential is ever present in the model's context.

FastMCP derives each tool's JSON Schema from the Python type hints and validates
incoming arguments with Pydantic before the function body runs, so a malformed
tool call from the model fails at the protocol boundary rather than in SQL.

Run standalone (stdio transport, what the agent launches):
    python -m mcp_db_agent.server
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from . import database as db
from .database import QueryTimeout
from .guard import UnsafeQueryError

mcp = FastMCP(
    name="university-db",
    instructions=(
        "Read-only access to a normalised university records database. "
        "Call get_database_schema first, then compose a single SELECT and run it "
        "with run_select_query. Write statements are rejected."
    ),
)


@mcp.tool
def list_tables() -> dict:
    """List every table in the database with its row count.

    Use this for a quick inventory. For column names and foreign keys, prefer
    get_database_schema.
    """
    return {"tables": db.list_tables()}


@mcp.tool
def get_database_schema() -> dict:
    """Return the complete schema: all tables, columns, primary keys, foreign
    keys, indexes, and the relationship edge list.

    Call this before writing any SQL. The `relationships` list gives the exact
    join paths available, so JOIN conditions can be derived rather than guessed.
    """
    return db.full_schema()


@mcp.tool
def describe_table(
    table_name: Annotated[str, Field(description="Exact table name, e.g. 'enrollments'")],
) -> dict:
    """Describe one table: columns with types and nullability, primary key,
    foreign keys, indexes, row count, and its CREATE TABLE statement."""
    try:
        return db.describe(table_name)
    except ValueError as exc:
        return {"error": str(exc)}


@mcp.tool
def sample_table_rows(
    table_name: Annotated[str, Field(description="Exact table name")],
    limit: Annotated[int, Field(ge=1, le=20, description="Rows to return (1-20)")] = 5,
) -> dict:
    """Return a few real rows from a table.

    Use this to check how values are actually formatted before writing a WHERE
    clause — for example whether status holds 'active' or 'Active'.
    """
    try:
        return db.sample_rows(table_name, limit)
    except ValueError as exc:
        return {"error": str(exc)}


@mcp.tool
def run_select_query(
    sql: Annotated[str, Field(description="A single SELECT statement. No semicolon needed.")],
    max_rows: Annotated[int, Field(ge=1, le=500, description="Row cap (1-500)")] = 200,
) -> dict:
    """Execute one read-only SELECT and return the rows.

    Also returns execution_ms and whether the query plan used an index, so a slow
    query can be spotted and rewritten.

    Rejects anything that is not a single SELECT (INSERT/UPDATE/DELETE/DROP/
    ATTACH/PRAGMA/stacked statements). On rejection, an `error` field explains
    why — read it and correct the SQL rather than retrying the same statement.
    """
    try:
        result = db.run_select(sql, max_rows)
    except UnsafeQueryError as exc:
        return {"error": f"Rejected by read-only guard: {exc}", "blocked": True}
    except QueryTimeout as exc:
        return {"error": str(exc), "blocked": False}
    except Exception as exc:  # genuine SQL errors: unknown column, bad syntax, ...
        return {"error": f"SQL error: {exc}", "blocked": False}

    return {
        "columns": result.columns,
        "rows": result.rows,
        "row_count": result.row_count,
        "truncated": result.truncated,
        "execution_ms": result.execution_ms,
        "used_index": result.used_index,
        "full_table_scans": result.full_scans,
    }


@mcp.tool
def explain_query_plan(
    sql: Annotated[str, Field(description="A single SELECT statement to analyse")],
) -> dict:
    """Return SQLite's query plan for a SELECT without running it.

    'SEARCH ... USING INDEX' means the optimiser found an index; a bare 'SCAN'
    means every row of that table is read. Use this on queries that came back
    slow, then add an indexed filter or reorder the joins.
    """
    try:
        return db.explain(sql)
    except UnsafeQueryError as exc:
        return {"error": f"Rejected by read-only guard: {exc}", "blocked": True}
    except Exception as exc:
        return {"error": f"SQL error: {exc}"}


@mcp.tool
def get_query_log(
    limit: Annotated[int, Field(ge=1, le=100, description="How many recent queries")] = 20,
) -> dict:
    """Return recently executed queries with their timings and index usage.

    Useful for answering "which of my queries was slowest" and for the
    performance summary shown in the CLI and web UI.
    """
    return db.query_log(limit)


@mcp.resource("schema://university")
def schema_resource() -> dict:
    """The full database schema, exposed as an MCP resource.

    Resources are for context a client can attach up-front; the same data is
    available as a tool call for clients that only support tools.
    """
    return db.full_schema()


@mcp.prompt
def analyse_question(question: str) -> str:
    """A reusable prompt template that walks a client through the ReAct loop."""
    return (
        f"Answer this question about the university database: {question}\n\n"
        "Steps: (1) call get_database_schema, (2) identify the tables and join "
        "path, (3) write one SELECT, (4) run it with run_select_query, "
        "(5) if execution_ms is high or used_index is false, call "
        "explain_query_plan and rewrite, (6) answer in plain English with the "
        "numbers you actually retrieved."
    )


if __name__ == "__main__":
    # stdio transport: the banner and logs would otherwise be interleaved with
    # protocol traffic on the client's terminal.
    mcp.run(show_banner=False)
