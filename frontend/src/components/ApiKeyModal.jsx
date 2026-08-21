import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { useAuth } from '../context/AuthContext'

// Collects / updates the user's Nemotron API key, stored encrypted on their
// account via PUT /auth/nemotron-key. Shown automatically (and mandatorily)
// while the account has no key, or on demand via the header button to replace
// an existing key (e.g. after a 401 from an invalid one).
function ApiKeyModal({ open = false, onClose }) {
  const { user, setUser } = useAuth()
  const [draft, setDraft] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  // Mandatory first-time prompt (no key yet) can't be dismissed; the on-demand
  // update dialog can.
  const mandatory = Boolean(user && !user.has_nemotron_key)
  const visible = Boolean(user) && (mandatory || open)

  useEffect(() => {
    if (visible) {
      setDraft('')
      setError(null)
      setSaving(false)
    }
  }, [visible])

  if (!visible) return null

  async function handleSubmit(e) {
    e.preventDefault()
    const key = draft.trim()
    if (!key) return
    setSaving(true)
    setError(null)
    try {
      setUser(await api.saveNemotronKey(key))
      onClose?.()
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-overlay">
      <form className="modal" onSubmit={handleSubmit}>
        <h2>{mandatory ? 'Enter your Nemotron API key' : 'Update your Nemotron API key'}</h2>
        <p>
          Stored encrypted on your account. Used solely to call the Nemotron API
          on your behalf. Get one at build.nvidia.com (starts with{' '}
          <code>nvapi-</code>).
        </p>
        <input
          type="password"
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="nvapi-..."
        />
        {error && <p className="chat-error">{error}</p>}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          {!mandatory && (
            <button
              type="button"
              onClick={onClose}
              style={{
                background: 'transparent',
                border: '1px solid var(--border-strong)',
                color: 'var(--text-dim)',
              }}
            >
              Cancel
            </button>
          )}
          <button type="submit" disabled={!draft.trim() || saving}>
            {saving ? 'Saving...' : mandatory ? 'Continue' : 'Save key'}
          </button>
        </div>
      </form>
    </div>
  )
}

export default ApiKeyModal
