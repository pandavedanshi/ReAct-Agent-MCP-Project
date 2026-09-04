import { useState } from 'react'
import ResultTable from './ResultTable'

// Renders one Reason -> Act -> Observe cycle per step, which is the whole point
// of the UI: the agent's decision process should be inspectable, not hidden.

const LABELS = {
  reason:  { text: 'REASON',  cls: 'reason' },
  act:     { text: 'ACT',     cls: 'act' },
  observe: { text: 'OBSERVE', cls: 'observe' },
  answer:  { text: 'ANSWER',  cls: 'answer' },
  error:   { text: 'ERROR',   cls: 'error' },
}

function Observation({ result }) {
  if (!result || typeof result !== 'object') {
    return <span className="muted">{String(result)}</span>
  }
  if (result.error) return <span className="error-text">⚠️ {result.error}</span>

  if (Array.isArray(result.rows)) {
    return (
      <div>
        <div className="metrics">
          <span className="metric-badge">{result.row_count} rows</span>
          <span className="metric-badge">{result.execution_ms} ms</span>
          <span className={`metric-badge ${result.used_index ? 'ok' : 'warn'}`}>
            {result.used_index ? '✓ index' : '⚠ full scan'}
          </span>
        </div>
        <ResultTable columns={result.columns} rows={result.rows} limit={8} />
      </div>
    )
  }
  if (Array.isArray(result.tables)) {
    return (
      <span className="muted">
        schema for {result.tables.length} tables · {(result.relationships || []).length} FK edges
      </span>
    )
  }
  return <pre className="json">{JSON.stringify(result, null, 2).slice(0, 800)}</pre>
}

function StepRow({ step }) {
  const label = LABELS[step.kind] || { text: step.kind.toUpperCase(), cls: '' }
  const sql = step.arguments?.sql

  return (
    <div className={`step step-${label.cls}`}>
      <span className={`tag tag-${label.cls}`}>{label.text}</span>
      <div className="step-body">
        {step.kind === 'act' && (
          <>
            <code className="tool-name">{step.tool}</code>
            {sql ? (
              <pre className="sql">{sql}</pre>
            ) : (
              step.arguments &&
              Object.keys(step.arguments).length > 0 && (
                <span className="muted"> {JSON.stringify(step.arguments)}</span>
              )
            )}
          </>
        )}
        {step.kind === 'observe' && <Observation result={step.result} />}
        {(step.kind === 'reason' || step.kind === 'error') && <span>{step.content}</span>}
      </div>
      {step.kind === 'observe' && (
        <span className="timing">{step.duration_ms} ms</span>
      )}
    </div>
  )
}

export default function TraceView({ result }) {
  const [open, setOpen] = useState(false)
  const steps = (result.steps || []).filter((s) => s.kind !== 'answer')
  if (steps.length === 0) return null

  return (
    <div className="trace">
      <button className="trace-toggle" onClick={() => setOpen(!open)}>
        <span>{open ? '▾' : '▸'}</span>
        ReAct trace
        <span className="trace-meta">
          — {result.tool_calls} tool calls · {Math.round(result.total_ms)} ms
        </span>
      </button>
      {open && (
        <div className="trace-steps">
          {steps.map((step, i) => (
            <StepRow key={i} step={step} />
          ))}
        </div>
      )}
    </div>
  )
}
