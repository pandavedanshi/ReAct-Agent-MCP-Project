import { useState } from 'react'

export default function SchemaPanel({ schema }) {
  const [expanded, setExpanded] = useState(null)
  if (!schema) return <p className="muted" style={{ padding: '8px 4px' }}>Loading schema…</p>

  return (
    <div>
      {schema.tables.map((table) => {
        const isOpen = expanded === table.table
        return (
          <div key={table.table} className="schema-table">
            <button
              className={`schema-head ${isOpen ? 'open' : ''}`}
              onClick={() => setExpanded(isOpen ? null : table.table)}
            >
              <span className="table-name">{table.table}</span>
              <span className="row-count">{table.row_count}</span>
              <span className="chevron">›</span>
            </button>
            {isOpen && (
              <ul className="schema-cols">
                {table.columns.map((col) => (
                  <li key={col.name}>
                    <span className={col.primary_key ? 'pk' : ''}>{col.name}</span>
                    <span className="col-type">{col.type}</span>
                  </li>
                ))}
                {table.foreign_keys.map((fk) => (
                  <li key={fk.column} className="fk">
                    ↳ {fk.column} → {fk.references}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )
      })}
    </div>
  )
}
