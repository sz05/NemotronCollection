import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
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
  // The one in-flight turn, tagged with the chat it belongs to:
  // {sessionId, text}. The user may switch chats while Nemotron is
  // replying; this tag makes sure the reply is applied (or the optimistic
  // user message restored) only in that chat, never the one on screen.
  const [pending, setPending] = useState(null)
  const [error, setError] = useState(null)

  const activeSessionRef = useRef(sessionId)
  activeSessionRef.current = sessionId
  const pendingRef = useRef(pending)
  pendingRef.current = pending

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
        if (cancelled) return
        let history = data.messages
        // Coming back to a chat whose turn is still in flight: the user
        // message isn't persisted until Nemotron replies, so re-add the
        // optimistic copy on top of the stored history.
        const inFlight = pendingRef.current
        if (inFlight && inFlight.sessionId === sessionId) {
          history = [...history, { role: 'user', content: inFlight.text }]
        }
        setMessages(history)
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

  const sendingHere = pending?.sessionId === sessionId
  const ready =
    Boolean(sessionId && user?.has_nemotron_key) &&
    !pending &&
    !loading &&
    !feedbackPending

  async function handleSubmit(e) {
    e.preventDefault()
    const text = draft.trim()
    if (!text || !ready) return

    const sid = sessionId
    const isFirstMessage = messages.length === 0
    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setDraft('')
    setPending({ sessionId: sid, text })
    setError(null)

    try {
      const { reply } = await api.sendChatMessage(sid, text)
      // Only touch the screen if that chat is still the one being viewed;
      // otherwise the turn is already persisted server-side and will load
      // when the user returns to it.
      if (activeSessionRef.current === sid) {
        setMessages((prev) => [...prev, { role: 'assistant', content: reply }])
      }
      if (isFirstMessage) onFirstMessage?.(sid, text)
    } catch (err) {
      if (activeSessionRef.current === sid) {
        setError(err.message)
        // The failed turn was never persisted; drop the optimistic copy so
        // the view matches the server.
        setMessages((prev) =>
          prev[prev.length - 1]?.role === 'user' ? prev.slice(0, -1) : prev
        )
      }
    } finally {
      setPending(null)
    }
  }

  return (
    <section className="chat-view">
      <h2>Chat</h2>
      <div className="chat-messages">
        {loading && <p className="chat-loading">Loading history...</p>}
        {messages.map((m, i) => (
          <div key={i} className={`chat-message chat-message--${m.role}`}>
            <span className="chat-message-role">{m.role === 'user' ? 'You' : 'Nemotron'}</span>
            {m.role === 'assistant' ? (
              <div className="chat-message-body markdown-body">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
              </div>
            ) : (
              <div className="chat-message-body">{m.content}</div>
            )}
          </div>
        ))}
        {sendingHere && <p className="chat-loading">Nemotron is thinking...</p>}
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
          {pending ? 'Sending...' : 'Send'}
        </button>
      </form>
    </section>
  )
}

export default ChatView
