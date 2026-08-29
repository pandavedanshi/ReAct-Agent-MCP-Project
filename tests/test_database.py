"""Layers 2 and 3: the engine-level controls, plus schema introspection."""

import sqlite3

import pytest

from mcp_db_agent import database as db
from mcp_db_agent.guard import UnsafeQueryError


def test_connection_is_read_only():
    """Layer 3: the driver itself refuses a write on a mode=ro connection."""
    conn = db.connect()
    try:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("DELETE FROM students")
    finally:
        conn.close()


def test_authorizer_blocks_writes_that_bypass_the_guard():
    """Layer 2: even calling sqlite3 directly, the authorizer denies a write."""
    conn = db.connect()
    try:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("INSERT INTO departments (dept_name) VALUES ('Fake')")
    finally:
        conn.close()


def test_authorizer_blocks_internal_tables():
    conn = db.connect()
    try:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("SELECT name FROM sqlite_master").fetchall()
    finally:
        conn.close()


def test_run_select_returns_rows_and_timing():
    result = db.run_select("SELECT dept_name FROM departments ORDER BY dept_name")
    assert result.row_count == 6
    assert result.columns == ["dept_name"]
    assert result.execution_ms >= 0


def test_run_select_rejects_writes():
    with pytest.raises(UnsafeQueryError):
        db.run_select("DELETE FROM students")


def test_row_cap_is_enforced():
    result = db.run_select("SELECT * FROM enrollments", max_rows=10)
    assert result.row_count == 10
    assert result.truncated is True


def test_index_is_detected_on_a_foreign_key_lookup():
    result = db.run_select("SELECT * FROM enrollments WHERE student_id = 7")
    assert result.used_index is True


def test_full_scan_is_reported():
    """No index exists on students.first_name, so this must scan."""
    plan = db.explain("SELECT * FROM students WHERE first_name = 'Isha'")
    assert plan["used_index"] is False
    assert plan["full_table_scans"]


def test_multi_hop_join_uses_indexes():
    sql = """
        SELECT c.title, COUNT(*) AS enrolled
        FROM enrollments e
        JOIN course_offerings o ON o.offering_id = e.offering_id
        JOIN courses c ON c.course_id = o.course_id
        GROUP BY c.title
    """
    result = db.run_select(sql)
    assert result.row_count > 0
    assert result.used_index is True


def test_describe_reports_keys_and_indexes():
    info = db.describe("enrollments")
    assert info["row_count"] > 0
    assert {fk["column"] for fk in info["foreign_keys"]} == {"student_id", "offering_id"}
    assert any(i["columns"] == ["student_id"] for i in info["indexes"])


def test_describe_rejects_unknown_table():
    with pytest.raises(ValueError):
        db.describe("students; DROP TABLE students")


def test_full_schema_exposes_relationship_edges():
    schema = db.full_schema()
    assert len(schema["tables"]) == 7
    edges = {(e["from"], e["to"]) for e in schema["relationships"]}
    assert ("enrollments", "students.student_id") in edges
    assert ("course_offerings", "courses.course_id") in edges


def test_query_log_records_executions():
    before = len(db.QUERY_LOG)
    db.run_select("SELECT COUNT(*) AS n FROM students")
    log = db.query_log(limit=5)
    assert len(db.QUERY_LOG) == before + 1
    assert log["queries"][-1]["rows"] == 1
