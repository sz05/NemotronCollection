// Task 0.8: thin fetch wrapper pointed at the FastAPI backend.
// credentials: 'include' sends the httpOnly auth cookie on every call.
// The Nemotron key is stored server-side (encrypted) per user; an optional
// per-request header override is still supported.

// Prepend https:// if the env var was set without a scheme — a bare host is
// otherwise fetched as a path relative to the current page.
function normalizeBaseUrl(url) {
  if (!url) return 'http://localhost:8000'
  const trimmed = url.replace(/\/+$/, '')
  return /^https?:\/\//.test(trimmed) ? trimmed : `https://${trimmed}`
}

const API_BASE_URL = normalizeBaseUrl(import.meta.env.VITE_API_BASE_URL)

async function request(path, { method = 'GET', body, nemotronKey, signal } = {}) {
  const headers = { 'Content-Type': 'application/json' }
  if (nemotronKey) headers['X-Nemotron-Key'] = nemotronKey

  const res = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
    credentials: 'include',
    signal,
  })

  if (!res.ok) {
    let detail = await res.text().catch(() => '')
    try {
      detail = JSON.parse(detail).detail ?? detail
    } catch {
      /* not JSON, keep raw text */
    }
    const err = new Error(detail || `API ${method} ${path} failed: ${res.status}`)
    err.status = res.status
    throw err
  }

  const contentType = res.headers.get('content-type') || ''
  return contentType.includes('application/json') ? res.json() : res.text()
}

// Multipart variant: the browser must set the multipart boundary itself, so we
// deliberately do NOT set Content-Type when sending a FormData body.
async function requestForm(path, formData, { method = 'POST', nemotronKey, signal } = {}) {
  const headers = {}
  if (nemotronKey) headers['X-Nemotron-Key'] = nemotronKey

  const res = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers,
    body: formData,
    credentials: 'include',
    signal,
  })

  if (!res.ok) {
    let detail = await res.text().catch(() => '')
    try {
      detail = JSON.parse(detail).detail ?? detail
    } catch {
      /* not JSON, keep raw text */
    }
    const err = new Error(detail || `API ${method} ${path} failed: ${res.status}`)
    err.status = res.status
    throw err
  }

  const contentType = res.headers.get('content-type') || ''
  return contentType.includes('application/json') ? res.json() : res.text()
}

export const api = {
  health: () => request('/health'),

  // --- auth ---
  authConfig: () => request('/auth/config'),
  googleLogin: (credential) =>
    request('/auth/google', { method: 'POST', body: { credential } }),
  devLogin: (email) => request('/auth/dev-login', { method: 'POST', body: { email } }),
  logout: () => request('/auth/logout', { method: 'POST' }),
  me: () => request('/auth/me'),
  saveNemotronKey: (apiKey) =>
    request('/auth/nemotron-key', { method: 'PUT', body: { api_key: apiKey } }),

  // --- chats ---
  createSession: (taskId = null) =>
    request('/session', { method: 'POST', body: { task_id: taskId } }),
  listSessions: () => request('/sessions'),
  getSession: (sessionId) => request(`/sessions/${sessionId}`),
  sendChatMessage: (sessionId, message, { acknowledgeOfftopic = false } = {}) =>
    request('/chat', {
      method: 'POST',
      body: { session_id: sessionId, message, acknowledge_offtopic: acknowledgeOfftopic },
    }),

  // --- feedback ---
  getFeedbackQuestion: (sessionId) => request(`/feedback-question/${sessionId}`),
  submitFeedback: (sessionId, question, answer) =>
    request('/feedback', {
      method: 'POST',
      body: { session_id: sessionId, question, answer },
    }),

  // --- tasks / scoring / proof / leaderboard ---
  getTasks: () => request('/tasks'),
  getScore: (sessionId) => request(`/sessions/${sessionId}/score`),
  getTotalScore: () => request('/score/total'),
  getLeaderboard: (limit = 50) => request(`/leaderboard?limit=${limit}`),
  submitProof: (sessionId, formData) =>
    requestForm(`/sessions/${sessionId}/proof`, formData),
  getProofStatus: (sessionId) => request(`/sessions/${sessionId}/proof`),
}

const WS_BASE_URL = API_BASE_URL.replace(/^http/, 'ws')

export { API_BASE_URL, WS_BASE_URL }
