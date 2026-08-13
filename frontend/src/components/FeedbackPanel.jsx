import { useEffect, useRef, useState } from 'react'
import { api, WS_BASE_URL } from '../api/client'

// Task 3.5 (live push) + task 4.1 (answer input): distinct panel (separate
// from ChatView) connected over WebSocket to /ws/feedback/{sessionId}.
// The backend pushes a question the moment the decoupled background Gemini
// task (task 3.2) finishes -- no client polling. Answers post to
// POST /feedback (task 4.2).
function FeedbackPanel({ sessionId }) {
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
      }
    }

    return () => ws.close()
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
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  const canAnswer = Boolean(question) && !submitted && !submitting

  return (
    <aside className="feedback-panel">
      <h2>
        Feedback{' '}
        <span className={`ws-status ws-status--${connected ? 'connected' : 'disconnected'}`}>
          {connected ? '● live' : '○ connecting...'}
        </span>
      </h2>
      <p className="feedback-question">
        {submitted
          ? 'Thanks! Waiting for the next question...'
          : (question ?? 'Waiting for a question...')}
      </p>
      {error && <p className="chat-error">{error}</p>}
      <form className="feedback-answer" onSubmit={handleSubmit}>
        <textarea
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          placeholder="Your answer..."
          disabled={!canAnswer}
        />
        <button type="submit" disabled={!canAnswer || !answer.trim()}>
          {submitting ? 'Submitting...' : 'Submit'}
        </button>
      </form>
    </aside>
  )
}

export default FeedbackPanel
