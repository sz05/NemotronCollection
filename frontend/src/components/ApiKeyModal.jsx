import { useState } from 'react'
import { api } from '../api/client'
import { useAuth } from '../context/AuthContext'

// Collects the user's Nemotron API key once after login and stores it
// (encrypted) on their account via PUT /auth/nemotron-key. Shown only
// while the account has no key on file.
function ApiKeyModal() {
  const { user, setUser } = useAuth()
  const [draft, setDraft] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  if (!user || user.has_nemotron_key) return null

  async function handleSubmit(e) {
    e.preventDefault()
    const key = draft.trim()
    if (!key) return
    setSaving(true)
    setError(null)
    try {
      setUser(await api.saveNemotronKey(key))
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-overlay">
      <form className="modal" onSubmit={handleSubmit}>
        <h2>Enter your Nemotron API key</h2>
        <p>
          Stored encrypted on your account so you only enter it once. Used
          solely to call the Nemotron API on your behalf.
        </p>
        <input
          type="password"
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="nvapi-..."
        />
        {error && <p className="chat-error">{error}</p>}
        <button type="submit" disabled={!draft.trim() || saving}>
          {saving ? 'Saving...' : 'Continue'}
        </button>
      </form>
    </div>
  )
}

export default ApiKeyModal
