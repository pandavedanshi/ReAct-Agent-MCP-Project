export default function ResultTable({ columns, rows, limit = 20 }) {
  if (!rows || rows.length === 0) return <p className="muted">No rows returned.</p>

  const cols = columns && columns.length ? columns : Object.keys(rows[0])
  const visible = rows.slice(0, limit)

  return (
    <div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {cols.map((c) => (
                <th key={c}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((row, i) => (
              <tr key={i}>
                {cols.map((c) => (
                  <td key={c}>{row[c] === null || row[c] === undefined ? '—' : String(row[c])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length > visible.length && (
          <div className="table-hint">
            Showing {visible.length} of {rows.length} rows
          </div>
        )}
      </div>
    </div>
  )
}
