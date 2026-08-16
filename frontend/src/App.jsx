import { useCallback, useEffect, useState } from 'react'
import { api } from './api/client'
import ApiKeyModal from './components/ApiKeyModal'
import ChatSidebar from './components/ChatSidebar'
import ChatView from './components/ChatView'
import FeedbackPanel from './components/FeedbackPanel'
import LoginScreen from './components/LoginScreen'
import { useAuth } from './context/AuthContext'
import './App.css'

function App() {
  const { user } = useAuth()
  const [backendStatus, setBackendStatus] = useState('checking...')
  const [sessions, setSessions] = useState([])
  const [activeSessionId, setActiveSessionId] = useState(null)
  // True while a feedback question is awaiting an answer; blocks the chat
  // input (backend enforces the same rule with a 409 on /chat).
  const [feedbackPending, setFeedbackPending] = useState(false)

  useEffect(() => {
    api
      .health()
      .then((data) => setBackendStatus(data.status ?? 'unknown'))
      .catch(() => setBackendStatus('unreachable'))
  }, [])

  const refreshSessions = useCallback(() => {
    return api.listSessions().then(setSessions)
  }, [])

  // On login: load the user's chats and open the most recent one (or a
  // fresh session if they have none yet).
  useEffect(() => {
    if (!user) {
      setSessions([])
      setActiveSessionId(null)
      return
    }
    api.listSessions().then((list) => {
      setSessions(list)
      if (list.length > 0) {
        setActiveSessionId(list[0].id)
      } else {
        api.createSession().then((data) => {
          setActiveSessionId(data.id)
          return refreshSessions()
        })
      }
    })
  }, [user, refreshSessions])

  async function handleNewChat() {
    const data = await api.createSession()
    setActiveSessionId(data.id)
    setFeedbackPending(false)
    await refreshSessions()
  }

  function handleSelect(sessionId) {
    setActiveSessionId(sessionId)
    setFeedbackPending(false)
  }

  if (user === undefined) return null // auth state still loading
  if (user === null) return <LoginScreen />

  return (
    <div className="app-shell">
      <ApiKeyModal />
      <header className="app-header">
        <h1>Synthetic Data Collection Harness</h1>
        <span className={`backend-status backend-status--${backendStatus}`}>
          backend: {backendStatus}
        </span>
      </header>
      <main className="app-layout app-layout--with-sidebar">
        <ChatSidebar
          sessions={sessions}
          activeSessionId={activeSessionId}
          onSelect={handleSelect}
          onNewChat={handleNewChat}
        />
        <ChatView
          sessionId={activeSessionId}
          feedbackPending={feedbackPending}
          onFirstMessage={refreshSessions}
        />
        <FeedbackPanel sessionId={activeSessionId} onPendingChange={setFeedbackPending} />
      </main>
    </div>
  )
}

export default App
