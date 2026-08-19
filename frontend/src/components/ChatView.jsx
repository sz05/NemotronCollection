import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api } from '../api/client'
import { useAuth } from '../context/AuthContext'
import RelevanceWarningModal from './RelevanceWarningModal'

// Task 2.5: sends user messages to POST /chat and renders the conversation.
// The Nemotron key is resolved server-side from the user's account.
// feedbackPending: a feedback question is awaiting an answer in the side
// panel -- the next prompt is blocked until it's submitted (the backend
// also rejects /chat with a 409 in that state).
// onFirstMessage fires after the first turn of a chat so the sidebar can
// refresh its title.
function ChatView({ sessionId, feedbackPending, onFirstMessage, onSent }) {
  const { user } = useAuth()
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(false)
  const [draft, setDraft] = useState('')
  // Off-topic confirmation: when /chat returns a relevance_warning we stash the
  // warning plus the exact message so "Yes, continue" can resend it with the
  // acknowledge flag, and "No, go back" can restore it into the draft box.
  const [relevanceWarning, setRelevanceWarning] = useState(null)
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
    setDraft('')
    await sendMessage(text, false)
  }

  // Sends one turn. When acknowledgeOfftopic is false the backend may reply with
  // a relevance_warning instead of an answer; we surface the confirm dialog and
  // keep the optimistic user bubble so the resend flows straight through.
  async function sendMessage(text, acknowledgeOfftopic) {
    const sid = sessionId
    const isFirstMessage = messages.length === 0
    if (!acknowledgeOfftopic) {
      setMessages((prev) => [...prev, { role: 'user', content: text }])
    }
    setPending({ sessionId: sid, text })
    setError(null)

    try {
      const { reply, relevance_warning } = await api.sendChatMessage(sid, text, {
        acknowledgeOfftopic,
      })
      if (activeSessionRef.current !== sid) return

      // Off-topic and not yet acknowledged: no answer was produced. Show the
      // confirm dialog; the optimistic user bubble stays on screen.
      if (relevance_warning && !acknowledgeOfftopic) {
        setRelevanceWarning({ warning: relevance_warning, text, sid })
        return
      }

      setMessages((prev) => [...prev, { role: 'assistant', content: reply }])
      if (isFirstMessage) onFirstMessage?.(sid, text)
      onSent?.(sid)
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

  function handleWarningContinue() {
    const w = relevanceWarning
    setRelevanceWarning(null)
    if (w) sendMessage(w.text, true)
  }

  function handleWarningCancel() {
    const w = relevanceWarning
    setRelevanceWarning(null)
    if (!w) return
    // Drop the optimistic user bubble and restore the text into the draft box.
    setMessages((prev) =>
      prev[prev.length - 1]?.role === 'user' ? prev.slice(0, -1) : prev
    )
    setDraft(w.text)
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
      <RelevanceWarningModal
        open={Boolean(relevanceWarning)}
        warning={relevanceWarning?.warning}
        onContinue={handleWarningContinue}
        onCancel={handleWarningCancel}
      />
    </section>
  )
}

export default ChatView
