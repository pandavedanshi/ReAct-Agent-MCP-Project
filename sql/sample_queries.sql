-- Reference queries. Useful for checking the agent's SQL against a known-good
-- answer, and for the `dbagent query "..."` demo path that needs no API key.

-- 1. Students per department, active only.
SELECT d.dept_name, COUNT(*) AS students, ROUND(AVG(s.cgpa), 2) AS avg_cgpa
FROM students s
JOIN departments d ON d.dept_id = s.dept_id
WHERE s.status = 'active'
GROUP BY d.dept_name
ORDER BY students DESC;

-- 2. Four-table join: average grade points per course.
SELECT c.course_code, c.title, COUNT(e.enrollment_id) AS enrolled,
       ROUND(AVG(e.grade_points), 2) AS avg_points
FROM courses c
JOIN course_offerings o ON o.course_id = c.course_id
JOIN enrollments e ON e.offering_id = o.offering_id
GROUP BY c.course_code, c.title
HAVING enrolled > 50
ORDER BY avg_points DESC;

-- 3. Teaching load per professor, across semesters.
SELECT p.first_name || ' ' || p.last_name AS professor, d.dept_name,
       COUNT(DISTINCT o.offering_id) AS offerings,
       COUNT(e.enrollment_id) AS total_students
FROM professors p
JOIN departments d ON d.dept_id = p.dept_id
LEFT JOIN course_offerings o ON o.prof_id = p.prof_id
LEFT JOIN enrollments e ON e.offering_id = o.offering_id
GROUP BY p.prof_id
ORDER BY total_students DESC
LIMIT 10;

-- 4. Grade distribution for one course.
SELECT e.grade, COUNT(*) AS n
FROM enrollments e
JOIN course_offerings o ON o.offering_id = e.offering_id
JOIN courses c ON c.course_id = o.course_id
WHERE c.course_code = 'CS202'
GROUP BY e.grade
ORDER BY e.grade;

-- 5. Window function: top 3 students per department by CGPA.
WITH ranked AS (
    SELECT s.first_name, s.last_name, s.cgpa, d.dept_name,
           ROW_NUMBER() OVER (PARTITION BY d.dept_id ORDER BY s.cgpa DESC) AS rn
    FROM students s
    JOIN departments d ON d.dept_id = s.dept_id
    WHERE s.status = 'active'
)
SELECT dept_name, first_name, last_name, cgpa FROM ranked WHERE rn <= 3;

-- 6. Semester-over-semester enrolment trend.
SELECT sem.year, sem.term, COUNT(e.enrollment_id) AS enrollments
FROM semesters sem
JOIN course_offerings o ON o.semester_id = sem.semester_id
JOIN enrollments e ON e.offering_id = o.offering_id
GROUP BY sem.year, sem.term
ORDER BY sem.year, sem.term;
