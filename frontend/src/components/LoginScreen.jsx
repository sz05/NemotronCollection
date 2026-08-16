import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { useAuth } from '../context/AuthContext'

const GSI_SRC = 'https://accounts.google.com/gsi/client'

// Full-page login gate. Google Sign-In renders when the backend has a
// GOOGLE_CLIENT_ID configured; the dev email login shows when DEV_AUTH is
// enabled (local testing before the Google credential exists).
function LoginScreen() {
  const { setUser } = useAuth()
  const [config, setConfig] = useState(null)
  const [email, setEmail] = useState('')
  const [error, setError] = useState(null)
  const googleButtonRef = useRef(null)

  useEffect(() => {
    api.authConfig().then(setConfig).catch(() => setError('Backend unreachable'))
  }, [])

  useEffect(() => {
    if (!config?.google_client_id) return

    function renderButton() {
      window.google.accounts.id.initialize({
        client_id: config.google_client_id,
        callback: async ({ credential }) => {
          try {
            setUser(await api.googleLogin(credential))
          } catch (err) {
            setError(err.message)
          }
        },
      })
      window.google.accounts.id.renderButton(googleButtonRef.current, {
        theme: 'filled_black',
        size: 'large',
        width: 280,
      })
    }

    if (window.google?.accounts?.id) {
      renderButton()
      return
    }
    const script = document.createElement('script')
    script.src = GSI_SRC
    script.async = true
    script.onload = renderButton
    script.onerror = () => setError('Failed to load Google Sign-In')
    document.head.appendChild(script)
  }, [config, setUser])

  async function handleDevLogin(e) {
    e.preventDefault()
    setError(null)
    try {
      setUser(await api.devLogin(email))
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <div className="login-screen">
      <div className="login-card">
        <h1>Synthetic Data Collection Harness</h1>
        <p>Sign in to keep your chats and pick up where you left off.</p>
        {config?.google_client_id && <div ref={googleButtonRef} className="google-button" />}
        {config && !config.google_client_id && !config.dev_auth && (
          <p className="chat-error">
            No login method configured — set GOOGLE_CLIENT_ID or DEV_AUTH in the backend .env.
          </p>
        )}
        {config?.dev_auth && (
          <form className="dev-login" onSubmit={handleDevLogin}>
            <span className="dev-login-label">Dev login (local only)</span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
            />
            <button type="submit" disabled={!email.trim()}>
              Continue
            </button>
          </form>
        )}
        {error && <p className="chat-error">{error}</p>}
      </div>
    </div>
  )
}

export default LoginScreen
