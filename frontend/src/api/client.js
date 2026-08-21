// Task 0.8: thin fetch wrapper pointed at the FastAPI backend.
// credentials: 'include' sends the httpOnly auth cookie on every call.
// The Nemotron key is stored server-side (encrypted) per user; an optional
// per-request header override is still supported.

// Prepend https:// if the env var was set without a scheme — a bare host is
// otherwise fetched as a path relative to the current page. Unset entirely
// (the combined-image default) means "same origin as this page" -- a plain
// '' base so fetches resolve relative to wherever the app is actually being
// served from, regardless of hostname/port/protocol.
function normalizeBaseUrl(url) {
  if (!url) return ''
  const trimmed = url.replace(/\/+$/, '')
  return /^https?:\/\//.test(trimmed) ? trimmed : `https://${trimmed}`
}

const API_BASE_URL = normalizeBaseUrl(import.meta.env.VITE_API_BASE_URL)

// CSRF double-submit: the server returns a token in the login / /auth/me body
// (the cookie itself is httpOnly). We stash it here and echo it in an
// X-CSRF-Token header on every state-changing request.
let csrfToken = null
const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS'])

// Capture a refreshed CSRF token from any response body that carries one.
function captureCsrf(data) {
  if (data && typeof data === 'object' && data.csrf_token) csrfToken = data.csrf_token
  return data
}

async function request(path, { method = 'GET', body, nemotronKey, signal } = {}) {
  const headers = { 'Content-Type': 'application/json' }
  if (nemotronKey) headers['X-Nemotron-Key'] = nemotronKey
  if (csrfToken && !SAFE_METHODS.has(method.toUpperCase())) headers['X-CSRF-Token'] = csrfToken

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
  return captureCsrf(contentType.includes('application/json') ? await res.json() : await res.text())
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

  // Streaming twin of sendChatMessage: reads the SSE response and invokes
  // onToken(text) for each answer delta. Returns { warning } if the backend
  // returned a relevance warning instead of an answer. Throws on error events.
  streamChatMessage: async (
    sessionId,
    message,
    { acknowledgeOfftopic = false, nemotronKey, signal, onToken } = {},
  ) => {
    const headers = { 'Content-Type': 'application/json' }
    if (nemotronKey) headers['X-Nemotron-Key'] = nemotronKey
    if (csrfToken) headers['X-CSRF-Token'] = csrfToken

    const res = await fetch(`${API_BASE_URL}/chat/stream`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        session_id: sessionId,
        message,
        acknowledge_offtopic: acknowledgeOfftopic,
      }),
      credentials: 'include',
      signal,
    })
    if (!res.ok || !res.body) {
      const err = new Error(`Chat stream failed: ${res.status}`)
      err.status = res.status
      throw err
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    let warning = null

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      // SSE frames are separated by a blank line.
      let sep
      while ((sep = buf.indexOf('\n\n')) !== -1) {
        const frame = buf.slice(0, sep)
        buf = buf.slice(sep + 2)
        const dataLine = frame.split('\n').find((l) => l.startsWith('data:'))
        if (!dataLine) continue
        const evt = JSON.parse(dataLine.slice(5).trim())
        if (evt.type === 'token') onToken?.(evt.content)
        else if (evt.type === 'relevance_warning') warning = evt
        else if (evt.type === 'error') throw new Error(evt.detail || 'Streaming error')
        // 'done' -> the reader will report done on the next read
      }
    }
    return { warning }
  },

  // --- feedback ---
  getFeedbackQuestion: (sessionId) => request(`/feedback-question/${sessionId}`),
  submitFeedback: (sessionId, question, answer) =>
    request('/feedback', {
      method: 'POST',
      body: { session_id: sessionId, question, answer },
    }),

  // --- tasks / scoring / submit / leaderboard ---
  getTasks: () => request('/tasks'),
  getScore: (sessionId) => request(`/sessions/${sessionId}/score`),
  getTotalScore: () => request('/score/total'),
  getLeaderboard: (limit = 50) => request(`/leaderboard?limit=${limit}`),
  // Submit the chat for Gemini scoring; returns { score, points, total_score }.
  submitChat: (sessionId) => request(`/sessions/${sessionId}/submit`, { method: 'POST' }),
  // Whether the Submit button is unlocked yet (+ best score so far).
  getSubmitStatus: (sessionId) => request(`/sessions/${sessionId}/submit-status`),

  // --- admin (allowlist-gated on the server) ---
  createTask: (task) => request('/tasks', { method: 'POST', body: task }),
}

const WS_BASE_URL = API_BASE_URL.replace(/^http/, 'ws')

export { API_BASE_URL, WS_BASE_URL }
