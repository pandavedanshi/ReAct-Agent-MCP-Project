"""Protocol-level tests: exercise the server the way the agent does.

Uses the in-memory transport, which still speaks MCP but skips the subprocess.
"""

import pytest

from mcp_db_agent.mcp_client import MCPToolbox

EXPECTED_TOOLS = {
    "list_tables", "get_database_schema", "describe_table", "sample_table_rows",
    "run_select_query", "explain_query_plan", "get_query_log",
}


@pytest.fixture
async def toolbox():
    async with MCPToolbox(transport="memory") as tb:
        yield tb


async def test_server_advertises_all_tools(toolbox):
    assert {t.name for t in toolbox.tools} == EXPECTED_TOOLS


async def test_every_tool_publishes_a_json_schema(toolbox):
    for spec in toolbox.tools:
        assert spec.input_schema.get("type") == "object"
        assert spec.description, f"{spec.name} has no description for the model to read"


async def test_list_tables(toolbox):
    result = await toolbox.call("list_tables", {})
    assert {t["table"] for t in result["tables"]} == {
        "departments", "professors", "students", "courses", "semesters",
        "course_offerings", "enrollments",
    }


async def test_select_through_the_protocol(toolbox):
    result = await toolbox.call(
        "run_select_query", {"sql": "SELECT COUNT(*) AS n FROM students"}
    )
    assert result["rows"][0]["n"] == 420
    assert "execution_ms" in result


@pytest.mark.parametrize("sql", [
    "DROP TABLE students",
    "UPDATE students SET cgpa = 10",
    "DELETE FROM enrollments",
    "SELECT 1; DROP TABLE students",
    "ATTACH DATABASE 'x' AS y",
])
async def test_write_attempts_are_blocked_over_the_protocol(toolbox, sql):
    result = await toolbox.call("run_select_query", {"sql": sql})
    assert result.get("blocked") is True
    assert "Rejected by read-only guard" in result["error"]


async def test_sql_errors_come_back_as_data_not_exceptions(toolbox):
    result = await toolbox.call(
        "run_select_query", {"sql": "SELECT nonexistent_column FROM students"}
    )
    assert "SQL error" in result["error"]
    assert result["blocked"] is False


async def test_pydantic_validation_rejects_out_of_range_arguments(toolbox):
    """max_rows is declared 1..500; FastMCP validates before the body runs."""
    result = await toolbox.call("run_select_query", {"sql": "SELECT 1", "max_rows": 9999})
    assert "error" in result


async def test_describe_table(toolbox):
    result = await toolbox.call("describe_table", {"table_name": "students"})
    assert result["row_count"] == 420
    assert any(c["primary_key"] for c in result["columns"])


async def test_describe_unknown_table_returns_error_field(toolbox):
    result = await toolbox.call("describe_table", {"table_name": "no_such_table"})
    assert "error" in result


async def test_explain_query_plan(toolbox):
    result = await toolbox.call(
        "explain_query_plan", {"sql": "SELECT * FROM enrollments WHERE student_id = 1"}
    )
    assert result["used_index"] is True
    assert result["plan"]


async def test_sample_rows_shows_real_values(toolbox):
    result = await toolbox.call("sample_table_rows", {"table_name": "students", "limit": 3})
    assert len(result["sample"]) == 3
    assert result["sample"][0]["status"] in {"active", "graduated", "on_leave", "withdrawn"}


async def test_schema_resource_is_readable(toolbox):
    payload = await toolbox.read_schema_resource()
    assert "relationships" in payload
