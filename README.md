# MCP-Enabled Database Query Agent

Ask a university database questions in plain English. A Gemini-powered **ReAct
agent** discovers the schema, writes SQL, runs it, and explains the answer — but
it never touches the database directly. Every read goes through a **FastMCP**
server that enforces a hard read-only boundary.

```
┌──────────┐   ┌──────────┐        ┌───────────────┐   MCP over    ┌──────────────┐        ┌────────────┐
│  React   │──▶│ FastAPI  │──────▶ │  ReAct Agent  │  stdio pipes  │ FastMCP      │───────▶│  SQLite    │
│    UI    │   │  bridge  │        │   (Gemini)    │◀─────────────▶│ server       │        │ (read-only)│
└──────────┘   └──────────┘        └───────────────┘               └──────────────┘        └────────────┘
     │                                     ▲                          7 tools                  3 guard
┌──────────┐                               │                       schema resource              layers
│   CLI    │───────────────────────────────┘
└──────────┘
```

The LLM sees tool names and JSON schemas. It never sees a file path, a
connection string, or a credential.

---

## Quick start

Four commands from a clean checkout.

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

# 2. Install
pip install -r requirements.txt
pip install -e .

# 3. Build the database (deterministic — always the same 4,339 rows)
python scripts/init_db.py

# 4. Add your free Gemini key
cp .env.example .env            # then edit .env and paste your key
```

Get a free key at **https://aistudio.google.com/apikey** (no billing account
required; the free tier is enough for this project).

### Run it

```bash
dbagent chat
```

```
you > Which department has the highest average grade points?

REASON I need the schema before I can name any tables.
ACT    get_database_schema
OBSERVE received database, note, relationships, tables (12 ms)
REASON Grades live in enrollments; department comes via students.
ACT    run_select_query
       SELECT d.dept_name, ROUND(AVG(e.grade_points), 2) AS avg_points
       FROM enrollments e
       JOIN students s ON s.student_id = e.student_id
       JOIN departments d ON d.dept_id = s.dept_id
       GROUP BY d.dept_name ORDER BY avg_points DESC
OBSERVE 6 rows in 3.7 ms (index) (18 ms)

╭─ Answer ─────────────────────────────────────────────────────────────╮
│ Management Studies has the highest average at 7.14 grade points,     │
│ narrowly ahead of Mathematics (7.06) and Computer Science (7.03).    │
╰──────────────────────────────────────────────────────────────────────╯
```

### Run the web UI

Two terminals:

```bash
# Terminal 1 — backend
uvicorn mcp_db_agent.api:app --reload

# Terminal 2 — frontend
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**. Three tabs: **chat** (agent + expandable ReAct
trace), **sql console** (run SQL yourself against the same guarded tool), and
**mcp tools** (what the server advertises).

---

## Rate limits — read this before demoing

Gemini's free tier is enforced **per model, per project** — a second API key in
the same project shares the same budget. Measured on AI Studio:

| Family | Requests/min | Tokens/min | Requests/**day** |
|---|---:|---:|---:|
| Flash — 3.5 / 3.6 / 3.7 | 5 | 250K | **20** |
| Flash-Lite — 3.1 / 3.5 | 15 | 250K | **500** |

One question costs 3–6 requests, so a single Flash model is good for about
**four questions per day**; a Lite model for roughly **a hundred**.

There is a trade-off: **only Flash models emit reasoning traces.** Lite models
answer just as correctly but show only ACT and OBSERVE — the REASON lines
disappear. The default chain is ordered to exploit that: Flash first for the
full ReAct trace, then Lite so a demo never runs dry.

> `gemini-2.5-flash` returns **404** for recently created keys — Google retired
> it for new projects. The agent detects this and switches model rather than
> failing.

### Four mechanisms

| # | Mechanism | Handles | Where |
|---|---|---|---|
| 1 | **Pacing** — sliding window, shared per model across the process, rate derived from the family (5 or 15/min) | Staying under the limit | [ratelimit.py](src/mcp_db_agent/ratelimit.py) |
| 2 | **Retry** using Google's own `RetryInfo` delay | Per-minute 429, transient 5xx | [agent.py](src/mcp_db_agent/agent.py) |
| 3 | **Model fallback** on a per-day 429 | Daily cap | [agent.py](src/mcp_db_agent/agent.py) |
| 4 | **Model fallback** on 404 | Retired models | [agent.py](src/mcp_db_agent/agent.py) |

Mechanisms 2 and 3 matter because a daily cap and a per-minute throttle are
*both* HTTP 429 with a ~30 s `retryDelay`. They are told apart only by the
`quotaId`: one ending in `PerDay` will not clear for hours, so retrying it
wastes time and burns quota that still counts against you.

A single real question exercising all four:

```
QUEUE  pacing gemini-3.6-flash to 5 req/min — next slot in 18s
SWITCH gemini-3.6-flash out of daily quota, switching to gemini-3.7-flash
RETRY  HTTP 503 (attempt 1) in 2s
ACT    get_database_schema
OBSERVE received database, note, relationships, tables (89 ms)
ACT    run_select_query
OBSERVE 2 rows in 0.6 ms (index)
```

For a live demo this is the difference between a working system and one that
fails in front of an interviewer for reasons unrelated to its design.

---

## No API key? Everything except the LLM still runs

```bash
dbagent tools                                   # what the MCP server exposes
dbagent schema                                  # the schema the agent sees
dbagent query "SELECT * FROM departments"       # SQL straight through MCP
dbagent query "DROP TABLE students"             # watch the guard reject it
dbagent resource                                # read the MCP schema resource
pytest -q                                       # all 85 tests
```

The web UI's **sql console** tab works without a key too.

---

## All commands

| Command | What it does | Needs a key |
|---|---|---|
| `dbagent chat` | Interactive REPL with live ReAct trace | yes |
| `dbagent ask "question"` | Answer one question and exit | yes |
| `dbagent query "SELECT ..."` | Run SQL through MCP, no LLM | no |
| `dbagent tools` | List the MCP server's tools | no |
| `dbagent schema` | Print tables, columns, FK edges | no |
| `dbagent resource` | Read the `schema://university` MCP resource | no |
| `python scripts/init_db.py` | Rebuild the database | no |
| `python scripts/build_report.py` | Regenerate `docs/report.pdf` | no |
| `uvicorn mcp_db_agent.api:app --reload` | Start the REST backend | no |
| `pytest -q` | Run the test suite | no |

In `chat`, type `reset` to clear conversation memory or `exit` to quit.

---

## The database

Seven tables in 3NF. The multi-hop path
`students → enrollments → course_offerings → courses → departments`
is deliberate: answering most questions requires a three- or four-table join,
which is what forces the agent to actually read the foreign-key graph.

```
departments ──┬─< professors ──┐
              ├─< courses ────┐│
              └─< students ─┐ ││
                            │ ││
        semesters ──< course_offerings >── (course, professor, semester)
                            │      │
                            └──< enrollments >──┘
```

| Table | Rows | Notes |
|---|---:|---|
| `departments` | 6 | |
| `professors` | 34 | FK → departments |
| `students` | 420 | FK → departments; `cgpa`, `status` |
| `courses` | 22 | FK → departments; unique `course_code` |
| `semesters` | 6 | unique `(term, year)` |
| `course_offerings` | 84 | junction: course × professor × semester |
| `enrollments` | 3,767 | junction: student × offering, carries `grade` |

Ten indexes cover every foreign key. SQLite indexes primary and unique keys
automatically but **not** foreign keys, so without them every join above would
degrade to a full table scan — see [`sql/schema.sql`](sql/schema.sql).

---

## Security: three independent layers

The point of the MCP boundary is that a compromised or confused LLM still cannot
write to the database. Each layer would stop a write on its own.

| Layer | Where | Mechanism |
|---|---|---|
| 1. Static analysis | [`guard.py`](src/mcp_db_agent/guard.py) | `sqlglot` parses the SQL; anything whose root is not `SELECT`, or whose tree contains `INSERT`/`UPDATE`/`DELETE`/`DROP`/`ALTER`/`ATTACH`/`PRAGMA`, is rejected. Stacked statements (`SELECT 1; DROP …`) are rejected by statement count. |
| 2. Engine authorizer | [`database.py`](src/mcp_db_agent/database.py) | `sqlite3.set_authorizer()` vetoes every operation that is not `SELECT`/`READ`/`FUNCTION`. It is an allowlist, so unknown verbs fail closed. |
| 3. Read-only handle | [`database.py`](src/mcp_db_agent/database.py) | The connection is opened as `file:university.db?mode=ro`. The driver itself refuses writes. |

Plus: a 5-second statement timeout via SQLite's progress handler, a row cap so
one query cannot flood the model's context, an 8 KB SQL length limit, and
`load_extension`/`readfile`/`writefile` blocked by name.

Try it:

```bash
dbagent query "SELECT 1; DROP TABLE students"
# Rejected by read-only guard: Only one statement per call is allowed (2 were supplied).
```

`tests/test_database.py` proves layers 2 and 3 independently: it calls
`sqlite3.execute("DELETE FROM students")` on a raw connection, bypassing the
guard entirely, and asserts the write still fails.

---

## Query optimisation

Every executed query reports its cost, so a bad plan is visible rather than
silent:

```json
{ "row_count": 6, "execution_ms": 3.75, "used_index": true, "full_table_scans": [] }
```

`used_index` comes from parsing `EXPLAIN QUERY PLAN`: SQLite prints
`SEARCH … USING INDEX` when an index drives the lookup and a bare `SCAN` when it
walks every row. The agent is instructed to call `explain_query_plan` and rewrite
whenever it sees `used_index: false` on a slow query. `get_query_log` returns the
whole session's timings.

```bash
dbagent query "SELECT * FROM enrollments WHERE student_id = 42"   # index used
dbagent query "SELECT * FROM students WHERE first_name = 'Isha'"  # full scan
```

---

## MCP tools

Defined in [`server.py`](src/mcp_db_agent/server.py). FastMCP generates each
JSON Schema from the Python type hints and validates arguments with Pydantic
before the function body runs.

| Tool | Purpose |
|---|---|
| `get_database_schema` | Full schema + foreign-key edge list. The agent's first call. |
| `list_tables` | Table names with row counts. |
| `describe_table` | Columns, keys, indexes, DDL for one table. |
| `sample_table_rows` | A few real rows, so the model sees that `status` is `'active'` and not `'Active'`. |
| `run_select_query` | Guarded execution; returns rows plus timing and index usage. |
| `explain_query_plan` | Query plan without executing. |
| `get_query_log` | Session history with timings. |

Also exposed: the `schema://university` **resource** and an `analyse_question`
**prompt** template, so all three MCP primitives are demonstrated.

Adding a tool means adding one `@mcp.tool` function — the agent picks it up on
its next start with no changes to `agent.py`. That decoupling is the whole point
of the protocol.

---

## Layout

```
├── src/mcp_db_agent/
│   ├── server.py       FastMCP server — the only code that opens the database
│   ├── guard.py        SQL safety analysis (layer 1)
│   ├── database.py     connections, authorizer, timing, plans (layers 2–3)
│   ├── agent.py        ReAct loop over Gemini function calling
│   ├── mcp_client.py   MCP client wrapper (stdio / in-memory transports)
│   ├── ratelimit.py    sliding-window request pacing
│   ├── cli.py          terminal interface
│   ├── api.py          FastAPI bridge for the browser
│   └── config.py       environment-driven settings
├── frontend/           React + Vite UI
├── sql/schema.sql      DDL, constraints, indexes
├── scripts/init_db.py  deterministic data generator
├── tests/              85 tests
└── docs/report.pdf     full project report
```

---

## Testing

```bash
pytest -q                           # 85 tests
pytest -v tests/test_guard.py       # 29 — 18 write / injection payloads rejected
pytest -v tests/test_database.py    # 13 — authorizer, read-only handle, plans
pytest -v tests/test_mcp_server.py  # 16 — every tool over the real protocol
pytest -v tests/test_agent.py       # 19 — ReAct loop, retries, quota/404 fallback
pytest -v tests/test_ratelimit.py   # 8  — sliding-window pacing on a fake clock
```

`tests/test_agent.py` replaces Gemini with a stub returning a fixed sequence of
responses, so the loop, tool dispatch, trace construction, conversation memory,
and step limit are all tested with no network call and no API key. The MCP
server and SQLite database underneath are real.

---

## Configuration

All optional; see [`.env.example`](.env.example).

| Variable | Default | Meaning |
|---|---|---|
| `GEMINI_API_KEY` | — | Required for the agent |
| `GEMINI_MODEL` | `gemini-3.6-flash` | Any Gemini model with function calling |
| `MAX_AGENT_STEPS` | `10` | ReAct iterations before giving up |
| `GEMINI_RPM` | `0` | Pacing req/min; `0` derives it from the model family |
| `GEMINI_FALLBACK_MODELS` | `gemini-3.7-flash,…` | Tried when a model is out of quota or retired |
| `MAX_RETRIES` | `4` | Attempts per Gemini call |
| `MAX_ROWS` | `200` | Row cap returned to the model |
| `QUERY_TIMEOUT_MS` | `5000` | Statement timeout |
| `MCP_TRANSPORT` | `stdio` | `stdio` (subprocess) or `memory` (in-process) |

---

## Troubleshooting

**`Database not found … Run: python scripts/init_db.py`** — the database is
generated, not committed. Run that command.

**`GEMINI_API_KEY is not set`** — create `.env` from `.env.example`. Only
`chat`/`ask` need it; `query`, `tools`, and `schema` do not.

**`Daily quota exhausted`** — that model's free-tier day is spent. The agent
falls back automatically; if every model in `GEMINI_FALLBACK_MODELS` is also
spent, wait for the reset (midnight Pacific) or use `dbagent query "<SQL>"`,
which needs no LLM.

**`Backend unreachable` in the browser** — start uvicorn first; the UI expects it
on port 8000.

**`dbagent: command not found`** — run `pip install -e .` with the venv active,
or use `python -m mcp_db_agent.cli` instead.

**Vite binds to IPv6 only on Windows** — use `http://localhost:5173`, not
`http://127.0.0.1:5173`.

---

## Report

[`docs/report.pdf`](docs/report.pdf) covers the architecture, design decisions,
the technologies used and why, a build walkthrough, benchmark numbers, and a
curated list of learning resources. Regenerate it with
`python scripts/build_report.py`.
