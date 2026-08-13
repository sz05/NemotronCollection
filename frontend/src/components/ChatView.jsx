import { useState } from 'react'
import { api } from '../api/client'
import { useNemotronKey } from '../context/NemotronKeyContext'

// Task 2.5: sends user messages to POST /chat and renders the conversation.
// Persistence (task 2.6) happens server-side in the /chat handler.
function ChatView({ sessionId }) {
  const { nemotronKey } = useNemotronKey()
  const [messages, setMessages] = useState([])
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState(null)

  const ready = Boolean(sessionId && nemotronKey) && !sending

  async function handleSubmit(e) {
    e.preventDefault()
    const text = draft.trim()
    if (!text || !ready) return

    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setDraft('')
    setSending(true)
    setError(null)

    try {
      const { reply } = await api.sendChatMessage(sessionId, text, nemotronKey)
      setMessages((prev) => [...prev, { role: 'assistant', content: reply }])
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
        {messages.map((m, i) => (
          <p key={i} className={`chat-message chat-message--${m.role}`}>
            <strong>{m.role === 'user' ? 'You' : 'Nemotron'}:</strong> {m.content}
          </p>
        ))}
        {error && <p className="chat-error">{error}</p>}
      </div>
      <form className="chat-input" onSubmit={handleSubmit}>
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Message Nemotron..."
          disabled={!sessionId || !nemotronKey}
        />
        <button type="submit" disabled={!ready || !draft.trim()}>
          {sending ? 'Sending...' : 'Send'}
        </button>
      </form>
    </section>
  )
}

export default ChatView
