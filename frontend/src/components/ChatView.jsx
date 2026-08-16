import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { useAuth } from '../context/AuthContext'

// Task 2.5: sends user messages to POST /chat and renders the conversation.
// The Nemotron key is resolved server-side from the user's account.
// feedbackPending: a feedback question is awaiting an answer in the side
// panel -- the next prompt is blocked until it's submitted (the backend
// also rejects /chat with a 409 in that state).
// onFirstMessage fires after the first turn of a chat so the sidebar can
// refresh its title.
function ChatView({ sessionId, feedbackPending, onFirstMessage }) {
  const { user } = useAuth()
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(false)
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState(null)

  // Load persisted history whenever the active chat changes.
  useEffect(() => {
    setMessages([])
    setError(null)
    if (!sessionId) return
    let cancelled = false
    setLoading(true)
    api
      .getSession(sessionId)
      .then((data) => {
        if (!cancelled) setMessages(data.messages)
      })
      .catch((err) => {
        if (!cancelled) setError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [sessionId])

  const ready =
    Boolean(sessionId && user?.has_nemotron_key) && !sending && !loading && !feedbackPending

  async function handleSubmit(e) {
    e.preventDefault()
    const text = draft.trim()
    if (!text || !ready) return

    const isFirstMessage = messages.length === 0
    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setDraft('')
    setSending(true)
    setError(null)

    try {
      const { reply } = await api.sendChatMessage(sessionId, text)
      setMessages((prev) => [...prev, { role: 'assistant', content: reply }])
      if (isFirstMessage) onFirstMessage?.(sessionId, text)
    } catch (err) {
      setError(err.message)
    } finally {
      setSending(false)
    }
  }

  return (
    <section className="chat-view">
      <h2>Chat</h2>
      <div className="chat-messages">
        {loading && <p className="chat-loading">Loading history...</p>}
        {messages.map((m, i) => (
          <p key={i} className={`chat-message chat-message--${m.role}`}>
            <strong>{m.role === 'user' ? 'You' : 'Nemotron'}:</strong> {m.content}
          </p>
        ))}
        {error && <p className="chat-error">{error}</p>}
      </div>
      {feedbackPending && (
        <p className="chat-feedback-gate">
          Answer the feedback question in the side panel to continue chatting.
        </p>
      )}
      <form className="chat-input" onSubmit={handleSubmit}>
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={feedbackPending ? 'Answer the feedback question first...' : 'Message Nemotron...'}
          disabled={!sessionId || feedbackPending}
        />
        <button type="submit" disabled={!ready || !draft.trim()}>
          {sending ? 'Sending...' : 'Send'}
        </button>
      </form>
    </section>
  )
}

export default ChatView
