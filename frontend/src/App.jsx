import { useEffect, useState } from 'react'
import { api } from './api/client'
import ApiKeyModal from './components/ApiKeyModal'
import ChatView from './components/ChatView'
import FeedbackPanel from './components/FeedbackPanel'
import { useNemotronKey } from './context/NemotronKeyContext'
import './App.css'

function App() {
  const [backendStatus, setBackendStatus] = useState('checking...')
  const [sessionId, setSessionId] = useState(null)
  const { nemotronKey } = useNemotronKey()

  useEffect(() => {
    api
      .health()
      .then((data) => setBackendStatus(data.status ?? 'unknown'))
      .catch(() => setBackendStatus('unreachable'))
  }, [])

  // Task 2.6 (setup): once the key is provided, create the DB-backed
  // ChatSession this tab's messages/feedback will be linked to.
  useEffect(() => {
    if (!nemotronKey || sessionId) return
    api
      .createSession()
      .then((data) => setSessionId(data.id))
      .catch(() => setSessionId(null))
  }, [nemotronKey, sessionId])

  return (
    <div className="app-shell">
      <ApiKeyModal />
      <header className="app-header">
        <h1>Synthetic Data Collection Harness</h1>
        <span className={`backend-status backend-status--${backendStatus}`}>
          backend: {backendStatus}
        </span>
      </header>
      <main className="app-layout">
        <ChatView sessionId={sessionId} />
        <FeedbackPanel sessionId={sessionId} />
      </main>
    </div>
  )
}

export default App
