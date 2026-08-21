import { useCallback, useEffect, useRef, useState } from 'react'
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
  // The task/theme locked to this chat (null for a free chat), shown on top.
  const [theme, setTheme] = useState(null)
  // Submit-to-score state. submitStatus = {can_submit, best_score}; submitResult
  // is the last 0-100 score the user got (only the score is surfaced, no rationale).
  const [submitStatus, setSubmitStatus] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [submitResult, setSubmitResult] = useState(null)
  const [submitError, setSubmitError] = useState(null)

  const activeSessionRef = useRef(sessionId)
  activeSessionRef.current = sessionId
  const pendingRef = useRef(pending)
  pendingRef.current = pending

  // Load persisted history whenever the active chat changes.
  useEffect(() => {
    setMessages([])
    setError(null)
    setTheme(null)
    if (!sessionId) return
    let cancelled = false
    setLoading(true)
    api
      .getSession(sessionId)
      .then((data) => {
        if (cancelled) return
        setTheme(data.theme ?? null)
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

  // Refresh whether the Submit button is unlocked. Recomputed on session switch
  // and after every sent turn (the unlock gate is a function of message count).
  const fetchSubmitStatus = useCallback((sid) => {
    if (!sid) return
    api.getSubmitStatus(sid).then(setSubmitStatus).catch(() => {})
  }, [])

  // On session switch: clear the last score and re-check the unlock state.
  useEffect(() => {
    setSubmitResult(null)
    setSubmitError(null)
    setSubmitStatus(null)
    if (sessionId) fetchSubmitStatus(sessionId)
  }, [sessionId, fetchSubmitStatus])

  async function handleSubmitChat() {
    const sid = sessionId
    setSubmitting(true)
    setSubmitError(null)
    try {
      const res = await api.submitChat(sid)
      if (activeSessionRef.current !== sid) return
      // Show POINTS (what actually moves the total) + the new total -- not the
      // raw 0-100 score, which reads as a discrepancy against the points total.
      setSubmitResult({ points: res.points, total: res.total_score })
      onSent?.(sid) // nudge ScorePanel to refetch the total
      fetchSubmitStatus(sid) // re-lock until the next threshold
    } catch (err) {
      if (activeSessionRef.current === sid) setSubmitError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

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

    // Tokens stream into one assistant bubble that's created on the first token,
    // so the relevance-warning path (no tokens) never leaves an empty bubble.
    let assistantStarted = false
    try {
      const { warning } = await api.streamChatMessage(sid, text, {
        acknowledgeOfftopic,
        onToken: (piece) => {
          if (activeSessionRef.current !== sid) return
          setMessages((prev) => {
            if (!assistantStarted) {
              assistantStarted = true
              return [...prev, { role: 'assistant', content: piece }]
            }
            const copy = prev.slice()
            const last = copy[copy.length - 1]
            if (last?.role === 'assistant') {
              copy[copy.length - 1] = { ...last, content: last.content + piece }
            }
            return copy
          })
        },
      })
      if (activeSessionRef.current !== sid) return

      // Off-topic and not yet acknowledged: no answer streamed. Show the confirm
      // dialog; the optimistic user bubble stays on screen.
      if (warning && !acknowledgeOfftopic) {
        setRelevanceWarning({ warning: { score: warning.score, message: warning.message }, text, sid })
        return
      }

      if (isFirstMessage) onFirstMessage?.(sid, text)
      onSent?.(sid)
      fetchSubmitStatus(sid) // this turn may have crossed the unlock threshold
    } catch (err) {
      if (activeSessionRef.current === sid) {
        setError(err.message)
        // The failed turn was never persisted; drop any partial assistant bubble
        // and the optimistic user copy so the view matches the server.
        setMessages((prev) => {
          let next = prev
          if (next[next.length - 1]?.role === 'assistant') next = next.slice(0, -1)
          if (next[next.length - 1]?.role === 'user') next = next.slice(0, -1)
          return next
        })
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
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0 }}>Chat</h2>
        {theme ? (
          <span
            title="This chat's locked theme"
            style={{
              padding: '4px 12px',
              borderRadius: 7,
              background: 'rgba(255,255,255,0.06)',
              color: '#c9cbd3',
              border: '1px solid rgba(255,255,255,0.15)',
              fontSize: 15,
              fontWeight: 600,
            }}
          >
            {theme}
          </span>
        ) : (
          sessionId && (
            <span style={{ color: '#9b9ca3', fontSize: 14 }}>Free chat</span>
          )
        )}
      </div>
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
        {sendingHere && messages[messages.length - 1]?.role !== 'assistant' && (
          <p className="chat-loading">Nemotron is thinking...</p>
        )}
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
      {sessionId && (
        <div className="submit-chat-bar">
          <button
            type="button"
            className="submit-chat-btn"
            onClick={handleSubmitChat}
            disabled={!submitStatus?.can_submit || submitting}
          >
            {submitting ? 'Scoring…' : 'Submit chat for scoring'}
          </button>
          {submitResult != null && (
            <p className="submit-chat-result">
              You earned <strong>{submitResult.points}</strong> pts · Total:{' '}
              <strong>{submitResult.total}</strong>
            </p>
          )}
          {submitError && <p className="submit-chat-error">{submitError}</p>}
          {!submitStatus?.can_submit && !submitting && submitResult == null && (
            <p className="submit-chat-hint">
              🔒 Keep chatting to unlock — explore the theme more, then submit.
            </p>
          )}
        </div>
      )}
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
