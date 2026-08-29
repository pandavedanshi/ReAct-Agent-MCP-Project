"""Generate docs/report.pdf.

Kept as a script rather than a checked-in binary so the report can be
regenerated whenever the project changes:  python scripts/build_report.py
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Flowable, Frame, KeepTogether, ListFlowable, ListItem,
    PageBreak, Paragraph, Preformatted, Spacer, Table, TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "report.pdf"

INK = colors.HexColor("#1a1a1a")
ACCENT = colors.HexColor("#1f4e79")
ACCENT_LIGHT = colors.HexColor("#e8eef5")
MUTED = colors.HexColor("#5a6672")
RULE = colors.HexColor("#c8d2dc")
CODE_BG = colors.HexColor("#f4f6f8")
OK = colors.HexColor("#1f7a3d")

# --------------------------------------------------------------------------
# Styles
# --------------------------------------------------------------------------
_base = getSampleStyleSheet()

S = {
    "title": ParagraphStyle("title", parent=_base["Title"], fontName="Helvetica-Bold",
                            fontSize=26, leading=31, textColor=ACCENT, spaceAfter=6),
    "subtitle": ParagraphStyle("subtitle", parent=_base["Normal"], fontSize=13, leading=18,
                               textColor=MUTED, alignment=TA_CENTER, spaceAfter=4),
    "h1": ParagraphStyle("h1", parent=_base["Heading1"], fontName="Helvetica-Bold",
                         fontSize=16, leading=20, textColor=ACCENT,
                         spaceBefore=16, spaceAfter=8, keepWithNext=1),
    "h2": ParagraphStyle("h2", parent=_base["Heading2"], fontName="Helvetica-Bold",
                         fontSize=12, leading=16, textColor=INK,
                         spaceBefore=12, spaceAfter=5, keepWithNext=1),
    "body": ParagraphStyle("body", parent=_base["Normal"], fontSize=10, leading=15,
                           textColor=INK, alignment=TA_JUSTIFY, spaceAfter=7),
    "bullet": ParagraphStyle("bullet", parent=_base["Normal"], fontSize=10, leading=14.5,
                             textColor=INK, spaceAfter=3),
    "code": ParagraphStyle("code", parent=_base["Code"], fontName="Courier", fontSize=7.6,
                           leading=10, textColor=INK, backColor=CODE_BG,
                           borderPadding=6, leftIndent=2, spaceBefore=4, spaceAfter=8),
    "cell": ParagraphStyle("cell", parent=_base["Normal"], fontSize=8.5, leading=12),
    "cellb": ParagraphStyle("cellb", parent=_base["Normal"], fontName="Helvetica-Bold",
                            fontSize=8.5, leading=12, textColor=colors.white),
    "caption": ParagraphStyle("caption", parent=_base["Normal"], fontSize=8.5, leading=12,
                              textColor=MUTED, alignment=TA_CENTER, spaceAfter=10),
}


# --------------------------------------------------------------------------
# Flowable helpers
# --------------------------------------------------------------------------
def h1(text):
    return Paragraph(text, S["h1"])


def h2(text):
    return Paragraph(text, S["h2"])


def p(text):
    return Paragraph(text, S["body"])


def code(text):
    # KeepTogether: a listing split across a page boundary is unreadable, and
    # leaves a near-empty page behind.
    return KeepTogether(Preformatted(text.strip("\n"), S["code"]))


def bullets(items):
    return ListFlowable(
        [ListItem(Paragraph(i, S["bullet"]), leftIndent=12) for i in items],
        bulletType="bullet", bulletFontSize=9, bulletOffsetY=-0.5,
        leftIndent=12, spaceAfter=8,
    )


def table(header, rows, widths):
    data = [[Paragraph(c, S["cellb"]) for c in header]]
    data += [[Paragraph(str(c), S["cell"]) for c in row] for row in rows]
    t = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ACCENT_LIGHT]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
        ("BOX", (0, 0), (-1, -1), 0.4, RULE),
    ]))
    return t


class Rule(Flowable):
    """A thin horizontal divider."""

    def __init__(self, width=None, thickness=0.7, colour=RULE):
        super().__init__()
        self.width, self.thickness, self.colour = width, thickness, colour
        self.height = thickness

    def wrap(self, aw, ah):
        self.width = self.width or aw
        return self.width, self.thickness + 6

    def draw(self):
        self.canv.setStrokeColor(self.colour)
        self.canv.setLineWidth(self.thickness)
        self.canv.line(0, 3, self.width, 3)


class Architecture(Flowable):
    """Vector diagram of the request path, drawn rather than ASCII-arted so it
    stays legible at print resolution."""

    # Constant, not self.height: reportlab overwrites self.height with the value
    # wrap() returns, and wrap() may be called more than once per layout pass.
    CONTENT_HEIGHT = 128

    def wrap(self, aw, ah):
        self.width = aw
        return aw, self.CONTENT_HEIGHT + 14

    def _box(self, x, y, w, h, title, sub, fill, stroke):
        c = self.canv
        c.setFillColor(fill)
        c.setStrokeColor(stroke)
        c.setLineWidth(0.9)
        c.roundRect(x, y, w, h, 4, stroke=1, fill=1)
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 8)
        c.drawCentredString(x + w / 2, y + h - 15, title)
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 6.6)
        for i, line in enumerate(sub):
            c.drawCentredString(x + w / 2, y + h - 26 - i * 8.5, line)

    def _arrow(self, x1, y, x2, label="", dashed=False):
        c = self.canv
        c.setStrokeColor(ACCENT)
        c.setLineWidth(0.9)
        c.setDash(2, 2) if dashed else c.setDash()
        c.line(x1, y, x2 - 4, y)
        c.setDash()
        c.setFillColor(ACCENT)
        head = c.beginPath()
        head.moveTo(x2, y)
        head.lineTo(x2 - 5, y + 2.6)
        head.lineTo(x2 - 5, y - 2.6)
        head.close()
        c.drawPath(head, stroke=0, fill=1)
        if label:
            # Painted above the shaft on a white patch so the line does not
            # strike through the text.
            c.setFont("Helvetica", 6)
            mid, width = (x1 + x2) / 2, c.stringWidth(label, "Helvetica", 6)
            c.setFillColor(colors.white)
            c.rect(mid - width / 2 - 1, y + 3.5, width + 2, 7, stroke=0, fill=1)
            c.setFillColor(MUTED)
            c.drawCentredString(mid, y + 5, label)

    def draw(self):
        c = self.canv
        gap, bh, y = 46, 62, 40
        bw = (self.width - 3 * gap) / 4
        xs = [i * (bw + gap) for i in range(4)]

        self._box(xs[0], y, bw, bh, "Interfaces",
                  ["React + Vite UI", "Rich CLI", "FastAPI bridge"],
                  colors.white, RULE)
        self._box(xs[1], y, bw, bh, "ReAct Agent",
                  ["Gemini 3.6 Flash", "function calling", "no DB credentials"],
                  ACCENT_LIGHT, ACCENT)
        self._box(xs[2], y, bw, bh, "FastMCP Server",
                  ["7 @mcp.tool", "Pydantic validation", "schema resource"],
                  ACCENT_LIGHT, ACCENT)
        self._box(xs[3], y, bw, bh, "SQLite",
                  ["7 tables, 3NF", "10 indexes", "mode=ro handle"],
                  colors.white, RULE)

        mid = y + bh / 2
        self._arrow(xs[0] + bw, mid, xs[1], "question")
        self._arrow(xs[1] + bw, mid, xs[2], "MCP / stdio")
        self._arrow(xs[2] + bw, mid, xs[3], "guarded SQL")

        # Trust boundary around the two components that never see the model's key
        # and the one component that never sees the database.
        c.setStrokeColor(colors.HexColor("#b03a2e"))
        c.setLineWidth(0.8)
        c.setDash(3, 3)
        c.roundRect(xs[2] - 12, y - 12, xs[3] + bw - xs[2] + 24, bh + 24, 5, stroke=1, fill=0)
        c.setDash()
        c.setFillColor(colors.HexColor("#b03a2e"))
        c.setFont("Helvetica-Bold", 6.4)
        c.drawString(xs[2] - 12, y - 21, "TRUST BOUNDARY — the LLM never crosses this line")


# --------------------------------------------------------------------------
# Page furniture
# --------------------------------------------------------------------------
def _decorate(canvas, doc):
    canvas.saveState()
    if doc.page > 1:
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.5)
        canvas.line(18 * mm, A4[1] - 15 * mm, A4[0] - 18 * mm, A4[1] - 15 * mm)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, A4[1] - 12.5 * mm, "MCP-Enabled Database Query Agent")
        canvas.drawRightString(A4[0] - 18 * mm, 12 * mm, str(doc.page))
    canvas.restoreState()


# --------------------------------------------------------------------------
# Content
# --------------------------------------------------------------------------
def story():
    s = []

    # ---------------- Cover ----------------
    s += [
        Spacer(1, 34 * mm),
        Paragraph("MCP-Enabled Database Query Agent", S["title"]),
        Paragraph("Natural-language querying over a relational database, "
                  "with a hard read-only boundary", S["subtitle"]),
        Spacer(1, 8),
        Rule(),
        Spacer(1, 12),
        Architecture(),
        Spacer(1, 14),
        table(
            ["Pillar", "Implementation"],
            [
                ["Agentic intelligence",
                 "ReAct loop (Reason &rarr; Act &rarr; Observe) over Gemini function calling, "
                 "with dynamic tool routing and conversational schema memory"],
                ["DBMS architecture",
                 "SQLite in 3NF: 7 tables, 10 indexes, 4,339 rows; three independent "
                 "read-only enforcement layers; per-query plan and latency tracking"],
                ["Protocol integration",
                 "FastMCP server exposing 7 tools, 1 resource and 1 prompt over stdio; "
                 "Pydantic validates every tool argument at the protocol boundary"],
            ],
            [34 * mm, 140 * mm],
        ),
        Spacer(1, 16),
        Paragraph("Python 3.13 &nbsp;&middot;&nbsp; FastMCP 3.4 &nbsp;&middot;&nbsp; "
                  "Google Gemini 3.6 Flash &nbsp;&middot;&nbsp; SQLite &nbsp;&middot;&nbsp; "
                  "FastAPI &nbsp;&middot;&nbsp; React 18 + Vite &nbsp;&middot;&nbsp; "
                  "85 passing tests", S["caption"]),
        PageBreak(),
    ]

    # ---------------- 1. Overview ----------------
    s += [
        h1("1. What the system does"),
        p("A user asks a question in English — <i>&ldquo;which department has the highest "
          "average grade points?&rdquo;</i> An agent works out which tables hold the answer, "
          "writes the SQL, runs it, and replies with the number it actually retrieved."),
        p("The interesting part is not the translation. It is that the language model is "
          "structurally incapable of damaging the database. It has no connection string, "
          "no file path, and no credential. It can only name a tool and supply arguments, "
          "and every tool that reaches data passes through three independent read-only "
          "controls. A prompt injection that convinces the model to drop a table produces "
          "a rejection message, not a dropped table."),
        p("That separation is what makes the architecture worth building. The intelligence "
          "layer and the data layer are joined by a narrow, typed, auditable protocol "
          "instead of a database driver."),

        h2("A worked example"),
        code("""
you > Which department has the highest average grade points?

REASON  I need the schema before I can name any tables.
ACT     get_database_schema
OBSERVE received database, note, relationships, tables            (12 ms)

REASON  Grades live in enrollments; department comes via students.
ACT     run_select_query
        SELECT d.dept_name, ROUND(AVG(e.grade_points), 2) AS avg_points
        FROM enrollments e
        JOIN students s     ON s.student_id = e.student_id
        JOIN departments d  ON d.dept_id    = s.dept_id
        GROUP BY d.dept_name
        ORDER BY avg_points DESC
OBSERVE 6 rows in 3.7 ms (index used)                             (18 ms)

ANSWER  Management Studies has the highest average at 7.14 grade points,
        narrowly ahead of Mathematics (7.06) and Computer Science (7.03).
"""),
        p("Three details are worth pointing out. The agent fetched the schema before "
          "naming a single table — it is not permitted to guess. It derived a three-table "
          "join from the foreign-key edge list rather than from memorised conventions. And "
          "the result carries its own cost report: 3.7 ms, index used."),
        PageBreak(),
    ]

    # ---------------- 2. Architecture ----------------
    s += [
        h1("2. Architecture"),
        Architecture(),
        Paragraph("Figure 1 — Request path. Every arrow is a process or protocol boundary.",
                  S["caption"]),
        p("Four layers, each replaceable without touching the others:"),
        table(
            ["Layer", "Module", "Responsibility"],
            [
                ["Interface", "cli.py, api.py, frontend/",
                 "Collect a question, render the answer and the reasoning trace. "
                 "Contains no database or model logic."],
                ["Agent", "agent.py",
                 "Run the ReAct loop. Translates between Gemini's function-calling format "
                 "and MCP tool calls. Holds conversation memory."],
                ["Protocol", "server.py, mcp_client.py",
                 "Advertise tools with JSON Schemas, validate arguments, dispatch calls. "
                 "The only crossing point between intelligence and data."],
                ["Data", "database.py, guard.py",
                 "Own every SQLite connection. Enforce read-only access, cap rows, "
                 "time queries, report query plans."],
            ],
            [24 * mm, 34 * mm, 116 * mm],
        ),

        h2("Why the boundary is real"),
        p("The MCP server runs as a <b>separate operating-system process</b>. The agent "
          "launches it and speaks JSON-RPC over its stdin and stdout pipes. Nothing in the "
          "agent's address space can reach a database handle; there is no import path from "
          "<font face='Courier'>agent.py</font> to <font face='Courier'>database.py</font>. "
          "Moving the server to another machine would be a transport change, not a rewrite."),
        p("An in-process transport is also available and is what the test suite uses: the "
          "same MCP messages, the same validation, no subprocess. Switching between them is "
          "one environment variable, which is itself a demonstration of what the protocol "
          "abstraction buys."),

        h2("Control flow of one question"),
        code("""
 1. CLI / React        collects the question
 2. Agent              appends it to history, calls Gemini with 7 tool declarations
 3. Gemini             returns a thought + a function_call
 4. Agent              forwards the call over MCP as tools/call
 5. FastMCP            validates arguments against the tool's Pydantic model
 6. guard.py           parses the SQL, rejects anything that is not one SELECT
 7. database.py        opens mode=ro handle, installs authorizer, EXPLAINs, executes
 8. Agent              appends the result as a function_response, loops to step 3
 9. Gemini             stops calling tools and answers in plain text
10. Interface          renders the answer plus the full REASON/ACT/OBSERVE trace
"""),
        PageBreak(),
    ]

    # ---------------- 3. Technology ----------------
    s += [
        h1("3. Technology choices"),
        p("Each choice below was made against a specific alternative. The reasoning matters "
          "more than the selection."),
        table(
            ["Component", "Chosen", "Why, and what was rejected"],
            [
                ["Protocol", "FastMCP 3.4",
                 "MCP is the emerging standard for connecting models to external systems — "
                 "one integration works with any MCP-capable client. FastMCP reduces a tool "
                 "to a decorated function and derives its JSON Schema from type hints. "
                 "Writing a bespoke REST API would have meant hand-maintaining schemas that "
                 "drift from the code."],
                ["LLM", "Gemini 3.6 Flash",
                 "Free at AI Studio, native parallel function calling, and exposed "
                 "reasoning traces (<font face='Courier'>include_thoughts</font>) that "
                 "become the REASON lines of the visible trace. The agent code is "
                 "provider-shaped only in one function; swapping providers means rewriting "
                 "<font face='Courier'>_to_function_declaration</font>."],
                ["Database", "SQLite",
                 "Zero-install, ships with Python, and — critically — supports both a "
                 "read-only connection URI and a per-operation authorizer callback, which "
                 "is what makes a genuinely layered security story possible. PostgreSQL "
                 "would give real read-only roles but requires a running server."],
                ["SQL parsing", "sqlglot",
                 "A real SQL parser produces an AST that can be walked for forbidden node "
                 "types. Regular expressions over SQL are defeated by comments, string "
                 "literals, and whitespace, and were rejected for that reason."],
                ["Validation", "Pydantic 2",
                 "Used by FastMCP to enforce argument types and ranges before a tool body "
                 "executes. A model that sends <font face='Courier'>max_rows=9999</font> "
                 "against a 1&ndash;500 bound is refused at the protocol layer."],
                ["Backend", "FastAPI",
                 "Async, so the single shared MCP session is not blocked by concurrent "
                 "requests; automatic OpenAPI docs at /docs."],
                ["Frontend", "React 18 + Vite",
                 "The UI's job is to make the ReAct trace inspectable, which is component "
                 "state. No UI framework or state library was added — the app is small "
                 "enough that hooks and plain CSS are the right size."],
                ["CLI", "Typer + Rich",
                 "Coloured, structured trace output in a terminal, which is how the project "
                 "is best demonstrated live."],
            ],
            [24 * mm, 27 * mm, 123 * mm],
        ),
        PageBreak(),
    ]

    # ---------------- 4. Database ----------------
    s += [
        h1("4. Database design"),
        p("Seven tables in third normal form. Normalisation is not decoration here: it is "
          "what makes the schema unambiguous enough for a model to navigate. Every fact is "
          "stored once, so there is exactly one correct join path to any answer, and the "
          "foreign-key graph fully describes it."),
        code("""
  departments  ---<  professors             one department, many professors
  departments  ---<  courses                one department, many courses
  departments  ---<  students               one department, many students

  course_offerings  --->  courses           which course is being taught
  course_offerings  --->  professors        who teaches it
  course_offerings  --->  semesters         when it runs

  enrollments  --->  students               who enrolled
  enrollments  --->  course_offerings       in which offering  (carries grade)

  ---<  one-to-many        --->  foreign key reference
"""),
        table(
            ["Table", "Rows", "Role"],
            [
                ["departments", "6", "Root entity"],
                ["professors", "34", "FK &rarr; departments"],
                ["students", "420", "FK &rarr; departments; cgpa, enrollment_year, status"],
                ["courses", "22", "FK &rarr; departments; unique course_code"],
                ["semesters", "6", "Unique (term, year)"],
                ["course_offerings", "84",
                 "Junction resolving course &times; professor &times; semester"],
                ["enrollments", "3,767",
                 "Junction resolving student &times; offering; carries grade and grade_points"],
            ],
            [32 * mm, 16 * mm, 126 * mm],
        ),
        Spacer(1, 6),
        p("The path <font face='Courier'>students &rarr; enrollments &rarr; course_offerings "
          "&rarr; courses &rarr; departments</font> is deliberate. Most interesting questions "
          "need three or four joins, so the agent cannot succeed by pattern-matching a "
          "single table — it has to read the relationship graph. That is the behaviour the "
          "schema was designed to force."),

        h2("Indexing"),
        p("SQLite indexes primary keys and unique constraints automatically, but "
          "<b>not</b> foreign keys. Without explicit indexes every join above would "
          "degrade to a nested full scan. Ten indexes cover all foreign keys plus two "
          "common filters, and <font face='Courier'>ANALYZE</font> runs at build time so "
          "the planner has statistics to cost them with."),
        table(
            ["Query", "Plan", "Latency"],
            [
                ["<font face='Courier'>WHERE student_id = 42</font>",
                 "SEARCH enrollments USING INDEX idx_enrollments_student", "0.044 ms"],
                ["<font face='Courier'>WHERE first_name = 'Isha'</font>",
                 "SCAN students <font color='#b03a2e'>(no index)</font>", "0.454 ms"],
                ["3-table join, GROUP BY department",
                 "SEARCH via idx_enrollments_student + PK lookups", "3.75 ms"],
                ["4-table join, GROUP BY course",
                 "SEARCH via idx_offerings_course + PK lookups", "4.44 ms"],
            ],
            [56 * mm, 92 * mm, 26 * mm],
        ),
        Spacer(1, 6),
        p("A ten-fold difference on 3,767 rows is small in absolute terms; the same ratio on "
          "a production table is the difference between a dashboard that loads and one that "
          "times out. The point of measuring it is that the agent is <i>told</i> the ratio "
          "and can act on it."),
        PageBreak(),
    ]

    # ---------------- 5. Security ----------------
    s += [
        h1("5. The read-only boundary"),
        p("This is the part of the system that has to survive scrutiny. A model can be "
          "talked into a destructive query by text it reads inside a database row, and it "
          "can simply hallucinate one. The design assumption is therefore that <b>the model "
          "will eventually emit a DELETE</b>, and the system must be correct when it does. "
          "Three controls sit in series; each would stop a write on its own, and they fail "
          "in different ways, so a bug in one does not compromise the others."),
        table(
            ["#", "Control", "Mechanism", "Defeated by"],
            [
                ["1", "Static analysis<br/><font size='7' color='#5a6672'>guard.py</font>",
                 "sqlglot parses the statement. The root must be SELECT; no INSERT, UPDATE, "
                 "DELETE, DROP, ALTER, ATTACH, PRAGMA or transaction node may appear "
                 "anywhere in the tree; exactly one statement is allowed.",
                 "A parser bug, or a construct sqlglot normalises away"],
                ["2", "Engine authorizer<br/><font size='7' color='#5a6672'>database.py</font>",
                 "sqlite3.set_authorizer() is consulted by the engine for every operation a "
                 "prepared statement attempts. Only SELECT, READ, FUNCTION and RECURSIVE are "
                 "allowed; it is an allowlist, so unknown verbs fail closed.",
                 "Nothing in-process — this runs inside SQLite"],
                ["3", "Read-only handle<br/><font size='7' color='#5a6672'>database.py</font>",
                 "The connection is opened as file:university.db?mode=ro. The driver itself "
                 "refuses any write before SQL is even considered.",
                 "Filesystem-level access outside the process"],
            ],
            [7 * mm, 33 * mm, 78 * mm, 56 * mm],
        ),
        Spacer(1, 8),
        p("Layer 1 exists mainly to produce a <i>useful error message</i> the agent can read "
          "and recover from. Layers 2 and 3 are what make a write impossible. Stating that "
          "distinction is the honest version of the defence: the friendly layer is not the "
          "one doing the security work."),

        h2("Supporting controls"),
        bullets([
            "<b>Stacked-statement rejection.</b> <font face='Courier'>SELECT 1; DROP TABLE "
            "students</font> is refused by statement count — the classic injection shape.",
            "<b>Row cap.</b> Results are limited (default 200) so one query cannot flood the "
            "model's context window; a probe row beyond the cap detects and reports truncation.",
            "<b>Statement timeout.</b> SQLite's progress handler interrupts any query running "
            "beyond 5 seconds, bounding an accidental cartesian join.",
            "<b>Internal tables blocked.</b> <font face='Courier'>sqlite_master</font> is "
            "denied by the authorizer; schema reaches the model only through the curated "
            "<font face='Courier'>describe_table</font> output.",
            "<b>Filesystem functions blocked.</b> <font face='Courier'>load_extension</font>, "
            "<font face='Courier'>readfile</font> and <font face='Courier'>writefile</font> "
            "are rejected by name.",
            "<b>Length limit.</b> Statements over 8 KB are refused before parsing.",
        ]),

        h2("How it is proved"),
        p("<font face='Courier'>tests/test_guard.py</font> fires 18 write and injection "
          "payloads at layer 1. More importantly, "
          "<font face='Courier'>tests/test_database.py</font> tests layers 2 and 3 "
          "<i>independently</i>: it calls "
          "<font face='Courier'>sqlite3.execute(\"DELETE FROM students\")</font> on a raw "
          "connection, bypassing the guard completely, and asserts the write still fails. "
          "A security layer that is only ever tested through the layer in front of it has "
          "not been tested."),
        code("""
$ dbagent query "SELECT 1; DROP TABLE students"
Rejected by read-only guard: Only one statement per call is allowed (2 were supplied).

$ dbagent query "ATTACH DATABASE '/etc/passwd' AS leak"
Rejected by read-only guard: ATTACH is not permitted
"""),
        PageBreak(),
    ]

    # ---------------- 6. Agent ----------------
    s += [
        h1("6. The ReAct agent"),
        p("ReAct interleaves reasoning with tool use instead of separating them. The model "
          "does not plan the whole query up front; it takes one step, sees the real result, "
          "and decides again. That is what lets it recover from its own mistakes."),
        table(
            ["Phase", "What happens"],
            [
                ["REASON", "Gemini produces a thought about what it still needs to know. "
                           "With <font face='Courier'>include_thoughts=True</font> this is "
                           "the model's genuine reasoning, not a paraphrase."],
                ["ACT", "It emits a <font face='Courier'>function_call</font>. The agent "
                        "forwards it over MCP without interpreting it."],
                ["OBSERVE", "The tool result is appended to the conversation as a "
                            "<font face='Courier'>function_response</font> and the loop "
                            "repeats, bounded at 10 iterations."],
            ],
            [22 * mm, 152 * mm],
        ),
        Spacer(1, 8),

        h2("Dynamic tool routing"),
        p("Tool declarations are generated at runtime from whatever the MCP server "
          "advertises. MCP publishes plain JSON Schema and the Gemini SDK accepts it "
          "verbatim through <font face='Courier'>parameters_json_schema</font>, so no "
          "field-by-field mapping exists that could drift:"),
        code("""
def _to_function_declaration(spec: ToolSpec) -> types.FunctionDeclaration:
    schema = dict(spec.input_schema)
    schema.pop("title", None)
    return types.FunctionDeclaration(
        name=spec.name,
        description=spec.description[:1024],
        parameters_json_schema=schema,      # MCP JSON Schema, passed straight through
    )
"""),
        p("The consequence: adding an <font face='Courier'>@mcp.tool</font> function to "
          "<font face='Courier'>server.py</font> makes it available to the model on the next "
          "start, with no change to <font face='Courier'>agent.py</font>. The interface is "
          "decoupled from the backend execution logic — which is the property the protocol "
          "exists to provide."),

        h2("Contextual memory"),
        p("Conversation history persists across turns on the agent instance, so the schema "
          "fetched for the first question is still in context for the fifth. Two things "
          "follow. Follow-ups work — <i>&ldquo;now break that down by year&rdquo;</i> "
          "resolves against the previous query. And the agent stops re-fetching the schema, "
          "because it already knows the join graph. Large observations are truncated before "
          "re-entering the context so a wide result set cannot crowd out the schema."),

        h2("Failure handling"),
        p("Tool errors are returned as data, never raised. A rejected write, a bad column "
          "name, or a timeout all arrive as an <font face='Courier'>error</font> field the "
          "model reads on its next turn — so it apologises and explains the read-only "
          "policy, or fixes the column name and retries. Raising would end the session; "
          "returning lets the loop do what it is for."),
        code("""
async def test_blocked_write_is_observed_not_raised(toolbox, scripted):
    scripted([
        _call("run_select_query", sql="DROP TABLE students"),
        _answer("That is not permitted; the database is read-only."),
    ])
    result = await DatabaseAgent(toolbox).ask("Delete all the students")

    observation = next(s for s in result.steps if s.kind == "observe").result
    assert observation["blocked"] is True
    assert "read-only guard" in observation["error"]
"""),
        PageBreak(),
    ]

    # ---------------- 6b. Quota engineering ----------------
    s += [
        h1("7. Operating inside a free-tier quota"),
        p("This section exists because the naive implementation did not survive "
          "contact with the real API, and the failure was instructive."),
        p("Gemini’s free tier enforces quotas <b>per model and per project</b> — a "
          "second API key in the same project shares the same budget. A single ReAct "
          "question spends three to six requests, one per loop iteration, so the daily "
          "column below is the binding constraint. An early test of five concurrent "
          "sessions exhausted the quota without a single one completing."),
        table(
            ["Model family", "Req/min", "Tokens/min", "Req/day", "Questions/day", "Reasoning trace"],
            [
                ["Flash — 3.5 / 3.6 / 3.7", "5", "250K", "20", "~4", "yes"],
                ["Flash-Lite — 3.1 / 3.5", "15", "250K", "500", "~100", "<b>no</b>"],
            ],
            [42 * mm, 18 * mm, 22 * mm, 18 * mm, 27 * mm, 27 * mm],
        ),
        Spacer(1, 6),
        p("The last column is the design tension. Only Flash models emit the thought "
          "summaries that become the REASON lines of the trace; Lite models answer just "
          "as correctly but show only ACT and OBSERVE. The fallback order therefore puts "
          "Flash first — the full trace while the small budget lasts — and Lite behind it, "
          "so a demonstration degrades in fidelity rather than stopping."),
        p("Four mechanisms address this, and they are deliberately different in kind: "
          "one avoids the limit, one recovers from it, and two route around it."),
        table(
            ["Mechanism", "Applies to", "How it works"],
            [
                ["Client-side pacing<br/><font size='7' color='#5a6672'>ratelimit.py</font>",
                 "Prevention",
                 "A sliding-window limiter admits at most N requests per 60 seconds, "
                 "holding the rest. It is shared per model across the process, so every "
                 "agent in the API server draws on one budget instead of each assuming it "
                 "owns the quota. A sliding rather than fixed window is used because a "
                 "fixed one permits a double-rate burst across its boundary — exactly the "
                 "pattern that trips Google’s limiter."],
                ["Retry with RetryInfo<br/><font size='7' color='#5a6672'>agent.py</font>",
                 "Per-minute 429",
                 "Reads the retryDelay Google returns rather than guessing, falling back "
                 "to exponential backoff when absent. Covers the case where another "
                 "process shares the key."],
                ["Model fallback<br/><font size='7' color='#5a6672'>agent.py</font>",
                 "Per-day 429",
                 "Switches to the next model in GEMINI_FALLBACK_MODELS. Each model has a "
                 "separate daily allowance, so an exhausted one is stepped over rather "
                 "than ending the session."],
                ["Model fallback<br/><font size='7' color='#5a6672'>agent.py</font>",
                 "404 Not Found",
                 "Google retires models for new keys — gemini-2.5-flash now 404s for "
                 "recently created projects. The old name never recovers, so this switches "
                 "model instead of retrying."],
            ],
            [34 * mm, 24 * mm, 116 * mm],
        ),
        Spacer(1, 8),

        h2("The distinction that matters"),
        p("A per-day exhaustion and a per-minute throttle are both HTTP 429, both carry "
          "RESOURCE_EXHAUSTED, and both suggest a retryDelay of about thirty seconds. "
          "Treating them alike is wrong in an expensive way: a daily cap will not clear "
          "for hours, so retrying wastes the user’s time and, because rejected requests "
          "still count against the quota, can eat into the next day’s allowance. The two "
          "are told apart only by the quotaId inside the QuotaFailure detail block."),
        code("""
def daily_quota_exhausted(exc):
    for entry in _error_details(exc):
        if "QuotaFailure" not in (entry.get("@type") or ""):
            continue
        for violation in entry.get("violations") or []:
            if "PerDay" in (violation.get("quotaId") or ""):
                return {"limit": violation.get("quotaValue"), ...}
    return None      # per-minute: safe to wait and retry
"""),
        p("Only when this returns a result does the agent stop retrying and change model."),

        h2("Observed behaviour"),
        p("One real question, exercising all four mechanisms in sequence — paced under "
          "the per-minute limit, stepped over an exhausted model, and retried a transient "
          "server error — before answering correctly:"),
        code("""
QUEUE   pacing gemini-3.6-flash to 5 req/min - next slot in 18s
SWITCH  gemini-3.6-flash out of daily quota, switching to gemini-3.7-flash
RETRY   HTTP 503 (attempt 1) in 2s
ACT     get_database_schema
OBSERVE received database, note, relationships, tables      (89 ms)
ACT     run_select_query
OBSERVE 2 rows in 0.6 ms (index)                            (55 ms)
"""),
        p("For a system that has to work during a live demonstration, this is the "
          "difference between a working project and one that fails in front of an "
          "audience for reasons unrelated to its design."),
        Spacer(1, 10),
    ]

    # ---------------- 7. MCP ----------------
    s += [
        h1("8. Protocol integration"),
        p("MCP standardises how a model reaches an external system — the same integration "
          "serves any MCP-capable client rather than being written once per model vendor. "
          "The server exposes all three MCP primitives."),
        table(
            ["Primitive", "Name", "Purpose"],
            [
                ["Tool", "get_database_schema",
                 "Full schema plus the foreign-key edge list. The agent's first call."],
                ["Tool", "list_tables", "Table names with row counts."],
                ["Tool", "describe_table", "Columns, keys, indexes and DDL for one table."],
                ["Tool", "sample_table_rows",
                 "A few real rows, so the model sees that status is 'active', not 'Active' "
                 "— a common source of silently-empty WHERE clauses."],
                ["Tool", "run_select_query",
                 "Guarded execution returning rows, timing and index usage."],
                ["Tool", "explain_query_plan", "Query plan without executing."],
                ["Tool", "get_query_log", "Session history with timings."],
                ["Resource", "schema://university",
                 "The schema as attachable context for clients that prefer resources."],
                ["Prompt", "analyse_question",
                 "A reusable template that walks any client through the ReAct loop."],
            ],
            [20 * mm, 38 * mm, 116 * mm],
        ),

        h2("What FastMCP removes"),
        p("A tool is a decorated function. Its JSON Schema comes from the type hints and its "
          "description from the docstring, so the contract the model sees and the code that "
          "runs cannot disagree:"),
        code("""
@mcp.tool
def run_select_query(
    sql: Annotated[str, Field(description="A single SELECT statement.")],
    max_rows: Annotated[int, Field(ge=1, le=500, description="Row cap (1-500)")] = 200,
) -> dict:
    \"\"\"Execute one read-only SELECT and return the rows.

    Rejects anything that is not a single SELECT. On rejection, an `error` field
    explains why - read it and correct the SQL rather than retrying unchanged.
    \"\"\"
"""),
        p("The docstring is not documentation for a human reader; it is the instruction the "
          "model acts on. Telling the model <i>what to do when a call fails</i> inside the "
          "tool description measurably reduces retry loops, which is why these docstrings "
          "read the way they do."),
        p("Pydantic enforces the bounds before the body runs. A model that sends "
          "<font face='Courier'>max_rows=9999</font> is refused at the protocol boundary "
          "with a schema error, not by defensive code inside the function."),

        h2("Transports"),
        table(
            ["Transport", "Shape", "Used for"],
            [
                ["stdio", "Server launched as a subprocess; JSON-RPC over pipes",
                 "Default. The real deployment shape — the server could equally be remote."],
                ["in-memory", "Client wired to the server object; identical MCP messages",
                 "Tests. 85 tests run in ~4 s with no process spawning."],
            ],
            [26 * mm, 74 * mm, 74 * mm],
        ),
        Spacer(1, 10),
    ]

    # ---------------- 8. Build walkthrough ----------------
    s += [
        h1("9. How it was built"),
        p("The order mattered. Each stage was verified before the next depended on it, so "
          "no failure could be ambiguous about its origin."),
        table(
            ["Stage", "Work", "Verified by"],
            [
                ["1. Schema",
                 "Model the domain in 3NF, add CHECK constraints and foreign keys, index "
                 "every FK, ANALYZE for planner statistics.",
                 "sqlite3 accepted the DDL; PRAGMA foreign_key_list returned the expected edges"],
                ["2. Data",
                 "Deterministic generator seeded with a fixed value, with realistic "
                 "correlations (the 2020 intake has mostly graduated; students take ~70% of "
                 "courses in their own department).",
                 "Rebuilds byte-identically, so every figure quoted in this report reproduces"],
                ["3. Guard",
                 "Allowlist SQL validation on a sqlglot AST.",
                 "18 attack payloads rejected, 6 legitimate query shapes accepted"],
                ["4. Data layer",
                 "Read-only URI, authorizer callback, progress-handler timeout, "
                 "EXPLAIN QUERY PLAN parsing, query log.",
                 "Raw sqlite3 writes bypassing the guard still fail"],
                ["5. MCP server",
                 "Seven @mcp.tool functions, one resource, one prompt.",
                 "A FastMCP client listed the tools and executed a 3-table join over the protocol"],
                ["6. Agent",
                 "ReAct loop; MCP schemas translated to Gemini function declarations; "
                 "trace capture; conversation memory.",
                 "Loop mechanics tested against a scripted model — no API key, real MCP and SQLite"],
                ["7. Interfaces",
                 "Rich CLI, FastAPI bridge with a shared MCP session, React UI with an "
                 "expandable trace view.",
                 "End-to-end: browser &rarr; Vite proxy &rarr; FastAPI &rarr; MCP &rarr; SQLite"],
            ],
            [22 * mm, 80 * mm, 72 * mm],
        ),

        h2("Two things that went wrong"),
        p("<b>Truncation was silently impossible to detect.</b> The row cap was implemented "
          "by appending <font face='Courier'>LIMIT max_rows</font> and then checking whether "
          "more than <font face='Courier'>max_rows</font> rows came back — which it never "
          "could, because SQL had already truncated them. The flag read "
          "<font face='Courier'>false</font> on every oversized result. A test caught it; "
          "the fix is to request one row beyond the cap as a probe and trim before "
          "returning. Worth noting because the bug was invisible from the outside: the data "
          "was correct, only the warning was missing."),
        p("<b>The MCP server's log output corrupted the CLI.</b> Under stdio transport the "
          "server's startup banner was written to the same stream the client renders, "
          "interleaving ASCII art with query results. Fixed by disabling the banner and "
          "raising the subprocess log level through the transport's environment — a "
          "reminder that with stdio transports, stdout belongs to the protocol."),
        PageBreak(),
    ]

    # ---------------- 9. Testing & results ----------------
    s += [
        h1("10. Testing and results"),
        table(
            ["Suite", "Tests", "What it establishes"],
            [
                ["test_guard.py", "29",
                 "18 write and injection payloads rejected; 6 legitimate shapes (CTE, UNION, "
                 "correlated subquery, multi-join) accepted; row-limit injection correct"],
                ["test_database.py", "13",
                 "Authorizer and read-only handle block writes independently of the guard; "
                 "index detection; FK introspection; row cap; query log"],
                ["test_mcp_server.py", "16",
                 "Every tool exercised over the real protocol; schemas well-formed; errors "
                 "returned as data; Pydantic bounds enforced"],
                ["test_agent.py", "19",
                 "ReAct loop, tool dispatch, trace construction, conversation memory, step "
                 "limit, retry/backoff, per-day vs per-minute quota, model fallback — "
                 "against a scripted model, with real MCP and SQLite underneath"],
                ["test_ratelimit.py", "8",
                 "Sliding-window pacing on a fake clock: window arithmetic, concurrent "
                 "callers never oversubscribing a window, per-model limiter sharing"],
            ],
            [34 * mm, 14 * mm, 126 * mm],
        ),
        Spacer(1, 8),
        p("<b>85 tests, ~4 seconds.</b> The suite needs no API key and no network, because "
          "the only non-deterministic component — the model — is the one part that is "
          "stubbed. Everything below it is real."),

        h2("Measured performance"),
        table(
            ["Operation", "Latency"],
            [
                ["Indexed foreign-key lookup", "0.04 ms"],
                ["Full scan of students (420 rows, unindexed column)", "0.45 ms"],
                ["Three-table join with GROUP BY", "3.75 ms"],
                ["Four-table join with GROUP BY and HAVING", "4.44 ms"],
                ["MCP tool round trip, in-memory transport", "&lt; 1 ms"],
                ["MCP tool round trip, stdio subprocess", "~10&ndash;20 ms"],
                ["Full agent turn (3 tool calls, Gemini 3.6 Flash)",
                 "2&ndash;5 s, dominated by model latency"],
                ["Full agent turn when paced against the free-tier quota",
                 "up to 60 s of deliberate waiting"],
            ],
            [120 * mm, 54 * mm],
        ),
        Spacer(1, 6),
        p("The model dominates end-to-end latency by three orders of magnitude. That is the "
          "argument for aggregating in SQL rather than pulling rows and computing in the "
          "loop: each avoided round trip saves seconds, while the query itself costs "
          "milliseconds."),

        h2("Honest limitations"),
        bullets([
            "<b>The model is not verified.</b> Guards prove the SQL is a read; nothing "
            "proves it answers the question asked. A semantically wrong but syntactically "
            "valid query returns a confident wrong answer. Mitigations used here — schema "
            "grounding, sample rows, forbidding invented numbers — reduce this but do not "
            "eliminate it.",
            "<b>Single-database scope.</b> The schema is fetched whole into context. A "
            "database with hundreds of tables would need retrieval over the schema rather "
            "than wholesale inclusion.",
            "<b>Server-side sessions.</b> Conversation state lives in process memory keyed "
            "by session id; it does not survive a restart and would not work across "
            "replicas without a shared store.",
            "<b>No authentication.</b> Every caller gets the same read-only view. "
            "Per-user row filtering would belong in the MCP server, not the agent — the "
            "agent must never be the component deciding what a user may see.",
            "<b>Free-tier throughput.</b> Roughly four questions per model per day "
            "(section 7). Pacing and model fallback make this survivable, not "
            "generous; sustained use needs a paid key.",
            "<b>No result caching.</b> The schema is re-fetched every session, costing "
            "one request out of a small daily budget that caching would recover.",
        ]),
        Spacer(1, 10),
    ]

    # ---------------- 10. Learning resources ----------------
    s += [
        h1("11. Learning resources"),
        p("Grouped by the concept each pillar depends on, with a note on what to take from "
          "each rather than a bare link."),

        h2("Model Context Protocol"),
        table(
            ["Resource", "Take from it"],
            [
                ["Official specification &mdash; modelcontextprotocol.io",
                 "The three primitives (tools, resources, prompts) and the lifecycle. Read "
                 "the architecture page before any tutorial."],
                ["FastMCP documentation &mdash; gofastmcp.com",
                 "Decorator API, transports, and the in-memory client used for testing here."],
                ["MCP Python SDK &mdash; github.com/modelcontextprotocol/python-sdk",
                 "The layer FastMCP sits on. Worth reading once to see the raw JSON-RPC "
                 "messages behind the abstraction."],
                ["Anthropic's MCP introduction (Nov 2024)",
                 "The design rationale — why a protocol rather than per-vendor plugins."],
            ],
            [66 * mm, 108 * mm],
        ),

        h2("Agentic patterns"),
        table(
            ["Resource", "Take from it"],
            [
                ["<i>ReAct: Synergizing Reasoning and Acting in Language Models</i>, "
                 "Yao et al., arXiv:2210.03629",
                 "The original paper. Short and readable; the interleaving argument is the "
                 "whole idea."],
                ["Gemini function-calling guide &mdash; ai.google.dev",
                 "Declaration format, parallel calls, and the manual loop this project uses "
                 "instead of automatic function calling."],
                ["<i>Building Effective Agents</i> &mdash; Anthropic engineering blog",
                 "When a loop is warranted and when a fixed pipeline is better. A useful "
                 "corrective to over-engineering."],
                ["<i>Prompt Engineering Guide</i> &mdash; promptingguide.ai",
                 "The ReAct and tool-use chapters, for how tool descriptions shape "
                 "behaviour."],
            ],
            [66 * mm, 108 * mm],
        ),

        h2("Database and security"),
        table(
            ["Resource", "Take from it"],
            [
                ["SQLite <i>Query Planner</i> and <i>EXPLAIN QUERY PLAN</i> docs",
                 "How to read SEARCH versus SCAN — directly what this project's "
                 "used_index flag is built on."],
                ["<i>Use of sqlite3_set_authorizer()</i> &mdash; sqlite.org",
                 "The exact mechanism behind security layer 2."],
                ["<i>Database System Concepts</i>, Silberschatz, Korth, Sudarshan",
                 "Chapters 7&ndash;8 for normalisation, 14 for indexing. The standard "
                 "reference if a normal-form question comes up."],
                ["<i>Use The Index, Luke</i> &mdash; use-the-index-luke.com",
                 "Practical, engine-agnostic indexing. The clearest explanation of why "
                 "unindexed foreign keys are so costly."],
                ["OWASP <i>SQL Injection Prevention Cheat Sheet</i>",
                 "Allowlist-over-denylist reasoning, which is the principle both the guard "
                 "and the authorizer follow."],
                ["OWASP <i>Top 10 for LLM Applications</i>",
                 "LLM01 Prompt Injection and LLM08 Excessive Agency name precisely the "
                 "threats this architecture is built against."],
            ],
            [66 * mm, 108 * mm],
        ),

        h2("Supporting stack"),
        table(
            ["Resource", "Take from it"],
            [
                ["sqlglot &mdash; github.com/tobymao/sqlglot",
                 "AST structure and the expression classes the guard walks."],
                ["FastAPI docs &mdash; lifespan events, dependency injection",
                 "The lifespan pattern used to share one MCP session across requests."],
                ["React docs (react.dev) &mdash; <i>Thinking in React</i>",
                 "State placement, which is the only real design question in this UI."],
                ["Pydantic v2 docs &mdash; validation and JSON Schema generation",
                 "What FastMCP does with type hints under the hood."],
            ],
            [66 * mm, 108 * mm],
        ),
        Spacer(1, 10),
    ]

    # ---------------- 11. Defence ----------------
    s += [
        h1("12. Anticipated questions"),
        p("The questions this design most invites, with the answers it supports."),
        table(
            ["Question", "Answer"],
            [
                ["<i>What stops the LLM dropping a table?</i>",
                 "Three independent controls, and the model never holds a database handle "
                 "in the first place. Layer 1 gives a readable rejection; layers 2 and 3 "
                 "make the write impossible. Layers 2 and 3 are tested by bypassing layer 1 "
                 "entirely — a security layer only ever tested through the one in front of "
                 "it is untested."],
                ["<i>Why MCP instead of a REST API?</i>",
                 "Schemas are generated from the code, so the model's view and the "
                 "implementation cannot drift. Any MCP-capable client can use the same "
                 "server. And the transport is swappable — this project runs the identical "
                 "server over a subprocess in production and in-process in tests."],
                ["<i>Why not let the model connect directly?</i>",
                 "Then the credential is in the model's context, every guard becomes advice "
                 "rather than enforcement, and there is no audit point. The narrow tool "
                 "interface is what makes the boundary enforceable."],
                ["<i>How do you know the SQL is correct?</i>",
                 "Correctness of intent is not proven, and that limitation is stated "
                 "plainly. What is enforced: the schema is read before any table is named, "
                 "join paths come from the declared foreign-key graph, sample rows show "
                 "real value formats, and the model is forbidden from stating a number no "
                 "tool returned. Every trace is inspectable, so a wrong answer is diagnosable."],
                ["<i>Why SQLite for a 'production-grade' system?</i>",
                 "Because it supports both a read-only handle and a per-operation "
                 "authorizer, which is what makes the layered defence demonstrable on any "
                 "machine. The data layer is one module; PostgreSQL would change that module "
                 "and gain real read-only roles and EXPLAIN ANALYZE."],
                ["<i>What happens if the model loops?</i>",
                 "Bounded at 10 iterations, after which the loop returns an explanatory "
                 "message. Each query is separately bounded by a 5-second timeout and a row "
                 "cap. Tested."],
                ["<i>How would you scale this?</i>",
                 "Move the MCP server behind HTTP transport and run several agent workers "
                 "against it; move session state to Redis; add per-user row filtering inside "
                 "the MCP server, never in the agent. Cache schema responses — they change "
                 "rarely and are fetched on every session."],
            ],
            [46 * mm, 128 * mm],
        ),

        h1("13. Possible extensions"),
        bullets([
            "<b>Result caching</b> keyed by normalised SQL, since schema and aggregate "
            "queries repeat heavily across a session — and, given the per-day request "
            "quota, caching the schema call alone would save one request per question.",
            "<b>Chart generation</b> — a tool returning a spec rather than an image, so the "
            "React layer renders it and the model never handles binary data.",
            "<b>Query approval mode</b> where the proposed SQL is shown for confirmation "
            "before execution — the standard pattern for higher-stakes deployments.",
            "<b>PostgreSQL adapter</b> behind the existing data-layer interface, adding real "
            "read-only roles and EXPLAIN ANALYZE.",
            "<b>Semantic evaluation set</b> — question/expected-answer pairs run in CI, "
            "which is the only real way to measure the correctness gap named in section 10.",
            "<b>Multi-database routing</b>, where the agent first selects a database and "
            "then a table, needed once the schema exceeds what fits in context.",
        ]),
        Spacer(1, 14),
        Rule(),
        Spacer(1, 6),
        Paragraph(
            "Source, setup instructions and troubleshooting: README.md in the project root. "
            "Regenerate this report with <font face='Courier'>python scripts/build_report.py</font>.",
            S["caption"]),
    ]
    return s


def build() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        str(OUT), pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=20 * mm, bottomMargin=18 * mm,
        title="MCP-Enabled Database Query Agent — Project Report",
        author="Project report",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body")
    from reportlab.platypus import PageTemplate
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=_decorate)])
    doc.build(story())
    print(f"Wrote {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    build()
