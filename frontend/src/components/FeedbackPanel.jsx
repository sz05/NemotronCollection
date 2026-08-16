import { useEffect, useRef, useState } from 'react'
import { api, WS_BASE_URL } from '../api/client'

// Task 3.5 (live push) + task 4.1 (answer input): feedback popup connected
// over WebSocket to /ws/feedback/{sessionId}. The backend pushes a question
// the moment the decoupled background Gemini task (task 3.2) finishes -- no
// client polling. Answers post to POST /feedback (task 4.2).
// The component stays mounted (the WebSocket must keep listening) but only
// renders a modal while a question is awaiting an answer. There is no close
// button on purpose: chat is gated until the question is answered (backend
// enforces this with a 409 on /chat).
// onPendingChange(true|false) tells the parent whether a question is
// currently awaiting an answer, so it can gate the chat input.
function FeedbackPanel({ sessionId, onPendingChange }) {
  const [question, setQuestion] = useState(null)
  const [connected, setConnected] = useState(false)
  const [answer, setAnswer] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [error, setError] = useState(null)
  const questionRef = useRef(question)
  questionRef.current = question

  useEffect(() => {
    if (!sessionId) return

    const ws = new WebSocket(`${WS_BASE_URL}/ws/feedback/${sessionId}`)

    ws.onopen = () => setConnected(true)
    ws.onclose = () => setConnected(false)
    ws.onerror = () => setConnected(false)
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      if (data.question && data.question !== questionRef.current) {
        setQuestion(data.question)
        setSubmitted(false)
        setAnswer('')
        setError(null)
        onPendingChange?.(true)
      }
    }

    return () => {
      ws.close()
      onPendingChange?.(false)
    }
  }, [sessionId])

  async function handleSubmit(e) {
    e.preventDefault()
    const text = answer.trim()
    if (!text || !question || !sessionId) return

    setSubmitting(true)
    setError(null)
    try {
      await api.submitFeedback(sessionId, question, text)
      setSubmitted(true)
      onPendingChange?.(false)
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  // Popup only while a question is awaiting an answer.
  if (!question || submitted) return null

  return (
    <div className="modal-overlay">
      <form className="modal modal--feedback" onSubmit={handleSubmit}>
        <h2>
          Feedback{' '}
          <span className={`ws-status ws-status--${connected ? 'connected' : 'disconnected'}`}>
            {connected ? '● live' : '○ connecting...'}
          </span>
        </h2>
        <p className="feedback-question">{question}</p>
        {error && <p className="chat-error">{error}</p>}
        <textarea
          autoFocus
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          placeholder="Your answer..."
          disabled={submitting}
        />
        <button type="submit" disabled={submitting || !answer.trim()}>
          {submitting ? 'Submitting...' : 'Submit'}
        </button>
      </form>
    </div>
  )
}

export default FeedbackPanel
