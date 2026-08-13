// Task 0.8: thin fetch wrapper pointed at the FastAPI backend.
// The Nemotron key (added in Phase 2) is attached per-request via an
// optional header, never stored here between calls.

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

async function request(path, { method = 'GET', body, nemotronKey, signal } = {}) {
  const headers = { 'Content-Type': 'application/json' }
  if (nemotronKey) headers['X-Nemotron-Key'] = nemotronKey

  const res = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
    signal,
  })

  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(`API ${method} ${path} failed: ${res.status} ${detail}`)
  }

  const contentType = res.headers.get('content-type') || ''
  return contentType.includes('application/json') ? res.json() : res.text()
}

export const api = {
  health: () => request('/health'),
  createSession: () => request('/session', { method: 'POST' }),
  sendChatMessage: (sessionId, message, nemotronKey) =>
    request('/chat', {
      method: 'POST',
      body: { session_id: sessionId, message },
      nemotronKey,
    }),
  getFeedbackQuestion: (sessionId) => request(`/feedback-question/${sessionId}`),
  submitFeedback: (sessionId, question, answer) =>
    request('/feedback', {
      method: 'POST',
      body: { session_id: sessionId, question, answer },
    }),
}

const WS_BASE_URL = API_BASE_URL.replace(/^http/, 'ws')

export { API_BASE_URL, WS_BASE_URL }
