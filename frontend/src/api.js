// Thin wrapper over the FastAPI backend. Vite proxies /api to port 8000 in dev.

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(body.detail || `Request failed (${response.status})`)
  }
  return body
}

export const getHealth = () => request('/api/health')
export const getSchema = () => request('/api/schema')
export const getTools = () => request('/api/tools')
export const getQueryLog = () => request('/api/query-log?limit=25')

export const ask = (question, sessionId) =>
  request('/api/ask', {
    method: 'POST',
    body: JSON.stringify({ question, session_id: sessionId }),
  })

export const runQuery = (sql) =>
  request('/api/query', { method: 'POST', body: JSON.stringify({ sql }) })

export const resetSession = (sessionId) =>
  request(`/api/reset?session_id=${encodeURIComponent(sessionId)}`, { method: 'POST' })
