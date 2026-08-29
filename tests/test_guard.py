"""Layer 1: static rejection of anything that is not a plain SELECT."""

import pytest

from mcp_db_agent.guard import UnsafeQueryError, apply_row_limit, validate

SAFE = [
    "SELECT 1",
    "SELECT * FROM students WHERE cgpa > 8",
    "SELECT d.dept_name, COUNT(*) FROM students s "
    "JOIN departments d ON d.dept_id = s.dept_id GROUP BY d.dept_name",
    "WITH ranked AS (SELECT student_id, cgpa FROM students) SELECT * FROM ranked LIMIT 5",
    "SELECT 1 UNION SELECT 2",
    "SELECT (SELECT COUNT(*) FROM enrollments) AS total",
]

UNSAFE = [
    "DROP TABLE students",
    "DELETE FROM students",
    "DELETE FROM students WHERE 1=1",
    "UPDATE students SET cgpa = 10",
    "INSERT INTO students (student_id) VALUES (999)",
    "CREATE TABLE evil (a INT)",
    "ALTER TABLE students ADD COLUMN backdoor TEXT",
    "SELECT 1; DROP TABLE students",
    "SELECT 1; DELETE FROM enrollments",
    "ATTACH DATABASE '/etc/passwd' AS leak",
    "DETACH DATABASE main",
    "PRAGMA writable_schema = ON",
    "VACUUM",
    "SELECT load_extension('evil.dll')",
    "SELECT * FROM sqlite_master",
    "REPLACE INTO students VALUES (1)",
    "",
    "   ",
]


@pytest.mark.parametrize("sql", SAFE)
def test_safe_queries_pass(sql):
    assert validate(sql).root_type in {"Select", "Union"}


@pytest.mark.parametrize("sql", UNSAFE)
def test_unsafe_queries_rejected(sql):
    with pytest.raises(UnsafeQueryError):
        validate(sql)


def test_oversized_query_rejected():
    with pytest.raises(UnsafeQueryError, match="exceeds"):
        validate("SELECT " + "1," * 5000 + "1")


def test_referenced_tables_are_reported():
    report = validate(
        "SELECT * FROM students s JOIN enrollments e ON e.student_id = s.student_id"
    )
    assert set(report.tables) == {"students", "enrollments"}


def test_row_limit_appended_when_absent():
    assert "LIMIT 50" in apply_row_limit("SELECT * FROM students", 50)


def test_existing_row_limit_preserved():
    assert "LIMIT 3" in apply_row_limit("SELECT * FROM students LIMIT 3", 50)


def test_trailing_semicolon_is_tolerated():
    assert validate("SELECT 1;").sql == "SELECT 1"
