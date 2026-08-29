-- University records schema, normalised to 3NF.
-- Every non-key attribute depends on the whole key and nothing but the key, so the
-- agent can resolve any question by following declared FK edges instead of guessing.

PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS enrollments;
DROP TABLE IF EXISTS course_offerings;
DROP TABLE IF EXISTS semesters;
DROP TABLE IF EXISTS courses;
DROP TABLE IF EXISTS students;
DROP TABLE IF EXISTS professors;
DROP TABLE IF EXISTS departments;

CREATE TABLE departments (
    dept_id     INTEGER PRIMARY KEY,
    dept_name   TEXT    NOT NULL UNIQUE,
    building    TEXT    NOT NULL,
    annual_budget REAL  NOT NULL CHECK (annual_budget >= 0)
);

CREATE TABLE professors (
    prof_id     INTEGER PRIMARY KEY,
    first_name  TEXT    NOT NULL,
    last_name   TEXT    NOT NULL,
    email       TEXT    NOT NULL UNIQUE,
    dept_id     INTEGER NOT NULL REFERENCES departments(dept_id),
    designation TEXT    NOT NULL CHECK (designation IN
                    ('Assistant Professor','Associate Professor','Professor','Lecturer')),
    hire_date   TEXT    NOT NULL
);

CREATE TABLE students (
    student_id      INTEGER PRIMARY KEY,
    first_name      TEXT    NOT NULL,
    last_name       TEXT    NOT NULL,
    email           TEXT    NOT NULL UNIQUE,
    dept_id         INTEGER NOT NULL REFERENCES departments(dept_id),
    enrollment_year INTEGER NOT NULL CHECK (enrollment_year BETWEEN 2000 AND 2100),
    cgpa            REAL    CHECK (cgpa BETWEEN 0 AND 10),
    status          TEXT    NOT NULL CHECK (status IN ('active','graduated','on_leave','withdrawn'))
);

CREATE TABLE courses (
    course_id   INTEGER PRIMARY KEY,
    course_code TEXT    NOT NULL UNIQUE,
    title       TEXT    NOT NULL,
    credits     INTEGER NOT NULL CHECK (credits BETWEEN 1 AND 6),
    dept_id     INTEGER NOT NULL REFERENCES departments(dept_id)
);

CREATE TABLE semesters (
    semester_id INTEGER PRIMARY KEY,
    term        TEXT    NOT NULL CHECK (term IN ('Spring','Autumn')),
    year        INTEGER NOT NULL,
    start_date  TEXT    NOT NULL,
    end_date    TEXT    NOT NULL,
    UNIQUE (term, year)
);

-- Resolves the many-to-many between a course and the semester/professor teaching it.
CREATE TABLE course_offerings (
    offering_id INTEGER PRIMARY KEY,
    course_id   INTEGER NOT NULL REFERENCES courses(course_id),
    prof_id     INTEGER NOT NULL REFERENCES professors(prof_id),
    semester_id INTEGER NOT NULL REFERENCES semesters(semester_id),
    room        TEXT    NOT NULL,
    capacity    INTEGER NOT NULL CHECK (capacity > 0),
    UNIQUE (course_id, semester_id, prof_id)
);

-- Junction table between students and offerings; grade_points is derived from grade
-- at insert time so aggregate GPA queries stay a single pass.
CREATE TABLE enrollments (
    enrollment_id INTEGER PRIMARY KEY,
    student_id    INTEGER NOT NULL REFERENCES students(student_id),
    offering_id   INTEGER NOT NULL REFERENCES course_offerings(offering_id),
    grade         TEXT    CHECK (grade IN ('A','A-','B+','B','B-','C+','C','D','F')),
    grade_points  REAL    CHECK (grade_points BETWEEN 0 AND 10),
    enrolled_on   TEXT    NOT NULL,
    UNIQUE (student_id, offering_id)
);

-- SQLite auto-indexes PRIMARY KEY and UNIQUE columns only. Foreign keys are not
-- indexed automatically, so every join path below would degrade to a full table
-- scan without these. explain_query_plan() surfaces whether the agent hit them.
CREATE INDEX idx_students_dept        ON students(dept_id);
CREATE INDEX idx_students_year_status ON students(enrollment_year, status);
CREATE INDEX idx_professors_dept      ON professors(dept_id);
CREATE INDEX idx_courses_dept         ON courses(dept_id);
CREATE INDEX idx_offerings_course     ON course_offerings(course_id);
CREATE INDEX idx_offerings_prof       ON course_offerings(prof_id);
CREATE INDEX idx_offerings_semester   ON course_offerings(semester_id);
CREATE INDEX idx_enrollments_student  ON enrollments(student_id);
CREATE INDEX idx_enrollments_offering ON enrollments(offering_id);
CREATE INDEX idx_enrollments_grade    ON enrollments(grade);
