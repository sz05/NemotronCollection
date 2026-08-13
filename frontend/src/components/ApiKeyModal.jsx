import { useState } from 'react'
import { useNemotronKey } from '../context/NemotronKeyContext'

// Task 2.1: prompt/modal that collects the user's Nemotron API key and
// holds it in the active session only (see NemotronKeyContext).
function ApiKeyModal() {
  const { nemotronKey, setNemotronKey } = useNemotronKey()
  const [draft, setDraft] = useState('')

  if (nemotronKey) return null

  function handleSubmit(e) {
    e.preventDefault()
    if (draft.trim()) setNemotronKey(draft.trim())
  }

  return (
    <div className="modal-overlay">
      <form className="modal" onSubmit={handleSubmit}>
        <h2>Enter your Nemotron API key</h2>
        <p>
          Held only in memory for this session. Never sent anywhere except
          the Nemotron API, and never saved to the database.
        </p>
        <input
          type="password"
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="nvapi-..."
        />
        <button type="submit" disabled={!draft.trim()}>
          Continue
        </button>
      </form>
    </div>
  )
}

export default ApiKeyModal
