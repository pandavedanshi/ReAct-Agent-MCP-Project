import { useEffect, useRef, useState } from 'react'
import * as api from './api'
import ResultTable from './components/ResultTable'
import SchemaPanel from './components/SchemaPanel'
import TraceView from './components/TraceView'

const SESSION_ID = `web-${Math.random().toString(36).slice(2, 10)}`

const EXAMPLES = [
  'Which department has the highest average grade points?',
  'List the top 5 students by CGPA in Computer Science',
  'How many students are enrolled in Database Management Systems?',
  'Which professor teaches the most course offerings?',
  'Show the grade distribution for Machine Learning',
]

const TOOL_ICONS = {
  get_database_schema: '🗄️',
  list_tables: '📋',
  describe_table: '🔍',
  sample_table_rows: '📄',
  run_select_query: '⚡',
  explain_query_plan: '🧭',
  get_query_log: '📜',
}

function Chat({ health }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const endRef = useRef(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, busy])

  async function submit(question) {
    if (!question.trim() || busy) return
    setMessages((m) => [...m, { role: 'user', text: question }])
    setInput('')
    setBusy(true)
    try {
      const result = await api.ask(question, SESSION_ID)
      setMessages((m) => [...m, { role: 'agent', result }])
    } catch (err) {
      setMessages((m) => [...m, { role: 'agent', error: err.message }])
    } finally {
      setBusy(false)
    }
  }

  async function clear() {
    await api.resetSession(SESSION_ID)
    setMessages([])
  }

  return (
    <div className="chat">
      {messages.length === 0 && (
        <div className="empty">
          <div className="empty-icon">🤖</div>
          <h2>Ask the university database anything</h2>
          <p>Powered by Gemini · ReAct reasoning · FastMCP · Read-only SQLite</p>

          {!health?.llm_configured && (
            <div className="warn-banner">
              ⚠️ No Gemini API key. Set <code>GEMINI_API_KEY</code> in <code>.env</code> and restart the backend — or use the SQL Console tab.
            </div>
          )}

          <div className="examples">
            {EXAMPLES.map((q) => (
              <button key={q} onClick={() => submit(q)}>
                {q}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="messages">
        {messages.map((msg, i) =>
          msg.role === 'user' ? (
            <div key={i} className="msg user">
              {msg.text}
            </div>
          ) : (
            <div key={i} className="msg agent">
              {msg.error ? (
                <p className="error-text">⚠️ {msg.error}</p>
              ) : (
                <>
                  <p className="answer">{msg.result.answer}</p>
                  {msg.result.sql_executed?.length > 0 && (
                    <pre className="sql">{msg.result.sql_executed.join('\n\n')}</pre>
                  )}
                  <TraceView result={msg.result} />
                </>
              )}
            </div>
          )
        )}
        {busy && (
          <div className="msg thinking">
            <div className="thinking-dots">
              <span /><span /><span />
            </div>
            Reasoning…
          </div>
        )}
        <div ref={endRef} />
      </div>

      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault()
          submit(input)
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="e.g. Which course has the lowest average grade?"
          disabled={busy}
        />
        <button type="submit" disabled={busy || !input.trim()}>
          {busy ? 'Thinking…' : '↑ Ask'}
        </button>
        <button type="button" className="ghost" onClick={clear} disabled={busy}>
          Clear
        </button>
      </form>
    </div>
  )
}

function SqlConsole() {
  const [sql, setSql] = useState(
    'SELECT d.dept_name, COUNT(*) AS students\nFROM students s\nJOIN departments d ON d.dept_id = s.dept_id\nGROUP BY d.dept_name\nORDER BY students DESC'
  )
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  async function run() {
    setBusy(true)
    setError(null)
    try {
      setResult(await api.runQuery(sql))
    } catch (err) {
      setError(err.message)
      setResult(null)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="console">
      <div className="console-desc">
        <span>🛡️</span>
        <span>
          Runs through the same MCP tool the agent uses — same read-only guard enforced.
          Try a <code>DROP TABLE</code> to watch it get rejected instantly.
        </span>
      </div>
      <textarea
        value={sql}
        onChange={(e) => setSql(e.target.value)}
        spellCheck={false}
        rows={8}
        placeholder="Write your SELECT query here…"
      />
      <button className="run-btn" onClick={run} disabled={busy}>
        {busy ? '⏳ Running…' : '▶ Run Query'}
      </button>
      {error && <p className="error-text">⚠️ {error}</p>}
      {result && (
        <div className="console-result">
          <div className="metrics">
            <span className="metric-badge">{result.row_count} rows</span>
            <span className="metric-badge">{result.execution_ms} ms</span>
            <span className={`metric-badge ${result.used_index ? 'ok' : 'warn'}`}>
              {result.used_index ? '✓ index used' : '⚠ full table scan'}
            </span>
          </div>
          <ResultTable columns={result.columns} rows={result.rows} limit={50} />
        </div>
      )}
    </div>
  )
}

function ToolsPanel({ tools }) {
  if (!tools) return <p className="muted" style={{ padding: '20px' }}>Loading tools…</p>
  return (
    <div className="tools">
      {tools.map((tool) => {
        const args = Object.keys(tool.schema.properties || {})
        return (
          <div key={tool.name} className="tool-card">
            <div className="tool-card-header">
              <div className="tool-icon">{TOOL_ICONS[tool.name] || '🔧'}</div>
              <code>{tool.name}</code>
            </div>
            <p>{tool.description.split('\n')[0]}</p>
            <div className="tool-args">
              {args.length === 0 ? (
                <span className="arg-chip">no arguments</span>
              ) : (
                args.map((a) => <span key={a} className="arg-chip">{a}</span>)
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

const TABS = [
  { id: 'chat',        label: 'Chat',       icon: '💬' },
  { id: 'sql console', label: 'SQL Console', icon: '⚡' },
  { id: 'mcp tools',  label: 'MCP Tools',  icon: '🔧' },
]

export default function App() {
  const [tab, setTab] = useState('chat')
  const [health, setHealth] = useState(null)
  const [schema, setSchema] = useState(null)
  const [tools, setTools] = useState(null)
  const [fatal, setFatal] = useState(null)

  useEffect(() => {
    Promise.all([api.getHealth(), api.getSchema(), api.getTools()])
      .then(([h, s, t]) => {
        setHealth(h)
        setSchema(s)
        setTools(t.tools)
      })
      .catch((err) => setFatal(err.message))
  }, [])

  if (fatal) {
    return (
      <div className="fatal">
        <div className="fatal-icon">⚠️</div>
        <h1>Backend Unreachable</h1>
        <p>{fatal}</p>
        <code>uvicorn mcp_db_agent.api:app --reload</code>
      </div>
    )
  }

  return (
    <div className="app">
      <header>
        <div className="header-brand">
          <div className="header-icon">🧠</div>
          <div className="header-title">
            <h1>MCP Database Query Agent</h1>
            <p>ReAct agent · FastMCP · SQLite (read-only)</p>
          </div>
        </div>
        {health && (
          <div className="status">
            <span className="badge-ok">{health.tools} MCP tools</span>
            <span className="badge">{health.transport}</span>
            <span className={health.llm_configured ? 'badge-ok' : 'badge-warn'}>
              {health.model}
            </span>
          </div>
        )}
      </header>

      <div className="layout">
        <aside>
          <div className="aside-header">
            <span className="aside-header-icon">🗄️</span>
            <h3>Database Schema</h3>
          </div>
          <SchemaPanel schema={schema} />
        </aside>

        <main>
          <nav className="tabs">
            {TABS.map((t) => (
              <button
                key={t.id}
                className={tab === t.id ? 'active' : ''}
                onClick={() => setTab(t.id)}
              >
                <span className="tab-icon">{t.icon}</span>
                {t.label}
              </button>
            ))}
          </nav>

          <div className="panel">
            {tab === 'chat' && <Chat health={health} />}
            {tab === 'sql console' && <SqlConsole />}
            {tab === 'mcp tools' && <ToolsPanel tools={tools} />}
          </div>
        </main>
      </div>
    </div>
  )
}
