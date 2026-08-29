"""Build data/university.db from sql/schema.sql and populate it with synthetic records.

Seeded with a fixed value so every run produces byte-identical data: the demo
queries quoted in the README always return the same numbers.
"""

from __future__ import annotations

import random
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "university.db"
SCHEMA_PATH = ROOT / "sql" / "schema.sql"

RNG = random.Random(20241201)

DEPARTMENTS = [
    ("Computer Science", "Turing Block", 12_500_000.0),
    ("Electrical Engineering", "Tesla Block", 9_800_000.0),
    ("Mechanical Engineering", "Newton Block", 8_400_000.0),
    ("Mathematics", "Gauss Hall", 5_200_000.0),
    ("Physics", "Bohr Hall", 6_100_000.0),
    ("Management Studies", "Drucker Wing", 7_300_000.0),
]

FIRST_NAMES = [
    "Aarav", "Isha", "Rohan", "Meera", "Kabir", "Ananya", "Vikram", "Priya",
    "Arjun", "Neha", "Siddharth", "Diya", "Rahul", "Tara", "Aditya", "Sneha",
    "Karthik", "Riya", "Manish", "Pooja", "Nikhil", "Aisha", "Varun", "Kavya",
]
LAST_NAMES = [
    "Sharma", "Iyer", "Nair", "Reddy", "Gupta", "Menon", "Bose", "Kulkarni",
    "Chatterjee", "Desai", "Malhotra", "Pillai", "Joshi", "Rao", "Verma", "Banerjee",
]

DESIGNATIONS = ["Assistant Professor", "Associate Professor", "Professor", "Lecturer"]

# Course catalogue keyed by index into DEPARTMENTS.
COURSES = {
    0: [("CS101", "Introduction to Programming", 4), ("CS201", "Data Structures", 4),
        ("CS202", "Database Management Systems", 4), ("CS301", "Operating Systems", 4),
        ("CS310", "Computer Networks", 3), ("CS402", "Machine Learning", 4),
        ("CS405", "Distributed Systems", 3)],
    1: [("EE101", "Circuit Theory", 4), ("EE205", "Digital Electronics", 4),
        ("EE301", "Signals and Systems", 3), ("EE350", "Control Systems", 3)],
    2: [("ME101", "Engineering Mechanics", 4), ("ME210", "Thermodynamics", 4),
        ("ME320", "Fluid Mechanics", 3)],
    3: [("MA101", "Linear Algebra", 4), ("MA202", "Probability and Statistics", 4),
        ("MA305", "Discrete Mathematics", 3)],
    4: [("PH101", "Classical Mechanics", 4), ("PH210", "Quantum Physics", 4)],
    5: [("MG101", "Principles of Management", 3), ("MG240", "Business Analytics", 3),
        ("MG310", "Operations Research", 4)],
}

# Grade -> (grade points on a 10-point scale, sampling weight).
GRADE_SCALE = [
    ("A", 10.0, 12), ("A-", 9.0, 16), ("B+", 8.0, 20), ("B", 7.0, 18),
    ("B-", 6.0, 12), ("C+", 5.0, 9), ("C", 4.0, 7), ("D", 3.0, 4), ("F", 0.0, 2),
]
GRADES = [g for g, _, _ in GRADE_SCALE]
GRADE_WEIGHTS = [w for _, _, w in GRADE_SCALE]
GRADE_POINTS = {g: p for g, p, _ in GRADE_SCALE}

ROOMS = ["LT-01", "LT-02", "LT-03", "Lab-A", "Lab-B", "Seminar-1", "Seminar-2"]
N_STUDENTS = 420
N_PROFESSORS = 34


def _unique_email(used: set, first: str, last: str, domain: str) -> str:
    base = f"{first.lower()}.{last.lower()}"
    email, n = f"{base}@{domain}", 1
    while email in used:
        n += 1
        email = f"{base}{n}@{domain}"
    used.add(email)
    return email


def build() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    cur = conn.cursor()
    emails: set = set()

    cur.executemany(
        "INSERT INTO departments (dept_id, dept_name, building, annual_budget) VALUES (?,?,?,?)",
        [(i + 1, name, bld, budget) for i, (name, bld, budget) in enumerate(DEPARTMENTS)],
    )

    professors = []
    for pid in range(1, N_PROFESSORS + 1):
        first, last = RNG.choice(FIRST_NAMES), RNG.choice(LAST_NAMES)
        hire = date(2005, 1, 1) + timedelta(days=RNG.randint(0, 7000))
        professors.append((
            pid, first, last, _unique_email(emails, first, last, "univ.edu"),
            RNG.randint(1, len(DEPARTMENTS)), RNG.choice(DESIGNATIONS), hire.isoformat(),
        ))
    cur.executemany(
        "INSERT INTO professors (prof_id, first_name, last_name, email, dept_id, designation,"
        " hire_date) VALUES (?,?,?,?,?,?,?)", professors)

    students = []
    for sid in range(1, N_STUDENTS + 1):
        first, last = RNG.choice(FIRST_NAMES), RNG.choice(LAST_NAMES)
        year = RNG.choice([2020, 2021, 2022, 2023, 2024])
        # The 2020 intake has mostly graduated; recent intakes are still active.
        weights = [10, 80, 5, 5] if year <= 2020 else [88, 2, 6, 4]
        status = RNG.choices(["active", "graduated", "on_leave", "withdrawn"], weights=weights)[0]
        students.append((
            sid, first, last, _unique_email(emails, first, last, "student.univ.edu"),
            RNG.randint(1, len(DEPARTMENTS)), year, round(RNG.uniform(5.2, 9.9), 2), status,
        ))
    cur.executemany(
        "INSERT INTO students (student_id, first_name, last_name, email, dept_id,"
        " enrollment_year, cgpa, status) VALUES (?,?,?,?,?,?,?,?)", students)

    courses, cid = [], 1
    for dept_index, catalogue in COURSES.items():
        for code, title, credits in catalogue:
            courses.append((cid, code, title, credits, dept_index + 1))
            cid += 1
    cur.executemany(
        "INSERT INTO courses (course_id, course_code, title, credits, dept_id) VALUES (?,?,?,?,?)",
        courses)

    semesters, sem_id = [], 1
    for year in (2022, 2023, 2024):
        for term, start, end in (("Spring", (1, 5), (5, 15)), ("Autumn", (8, 1), (12, 10))):
            semesters.append((sem_id, term, year,
                              date(year, *start).isoformat(), date(year, *end).isoformat()))
            sem_id += 1
    cur.executemany(
        "INSERT INTO semesters (semester_id, term, year, start_date, end_date) VALUES (?,?,?,?,?)",
        semesters)

    # Every course runs in roughly two thirds of the semesters, taught by a
    # professor drawn from its own department.
    profs_by_dept: dict = {}
    for prof in professors:
        profs_by_dept.setdefault(prof[4], []).append(prof[0])

    offerings, off_id = [], 1
    for course_id, _code, _title, _credits, dept_id in courses:
        for semester in semesters:
            if RNG.random() > 0.62:
                continue
            faculty = profs_by_dept.get(dept_id) or [RNG.randint(1, N_PROFESSORS)]
            offerings.append((off_id, course_id, RNG.choice(faculty), semester[0],
                              RNG.choice(ROOMS), RNG.choice([40, 60, 80, 120])))
            off_id += 1
    cur.executemany(
        "INSERT INTO course_offerings (offering_id, course_id, prof_id, semester_id, room,"
        " capacity) VALUES (?,?,?,?,?,?)", offerings)

    course_dept = {c[0]: c[4] for c in courses}
    offerings_by_dept: dict = {}
    for off in offerings:
        offerings_by_dept.setdefault(course_dept[off[1]], []).append((off[0], off[3]))

    sem_start = {s[0]: s[3] for s in semesters}
    enrollments, enr_id = [], 1
    for student in students:
        sid, student_dept, joined = student[0], student[4], student[5]
        in_dept = offerings_by_dept.get(student_dept, [])
        electives = [o for d, offs in offerings_by_dept.items() if d != student_dept for o in offs]
        chosen = RNG.sample(in_dept, min(len(in_dept), RNG.randint(6, 12)))
        chosen += RNG.sample(electives, min(len(electives), RNG.randint(1, 4)))
        for offering_id, semester_id in chosen:
            if int(sem_start[semester_id][:4]) < joined:
                continue  # cannot enrol in a semester that predates admission
            grade = RNG.choices(GRADES, weights=GRADE_WEIGHTS)[0]
            enrollments.append((enr_id, sid, offering_id, grade, GRADE_POINTS[grade],
                                sem_start[semester_id]))
            enr_id += 1
    cur.executemany(
        "INSERT INTO enrollments (enrollment_id, student_id, offering_id, grade, grade_points,"
        " enrolled_on) VALUES (?,?,?,?,?,?)", enrollments)

    conn.commit()
    conn.execute("ANALYZE")  # populate sqlite_stat1 so the planner costs indexes correctly
    conn.commit()

    tables = ("departments", "professors", "students", "courses", "semesters",
              "course_offerings", "enrollments")
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
    conn.close()

    print(f"Built {DB_PATH}")
    for table, n in counts.items():
        print(f"  {table:<18} {n:>6} rows")


if __name__ == "__main__":
    try:
        build()
    except Exception as exc:
        print(f"init_db failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
