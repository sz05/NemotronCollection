import { createContext, useContext, useState } from 'react'

// Task 2.1/2.2: the Nemotron key lives only in React state for the active
// tab session -- never localStorage/sessionStorage/cookies, so it doesn't
// outlive a reload and is never sent anywhere except the per-request
// X-Nemotron-Key header attached by api/client.js.
const NemotronKeyContext = createContext(null)

export function NemotronKeyProvider({ children }) {
  const [nemotronKey, setNemotronKey] = useState('')
  return (
    <NemotronKeyContext.Provider value={{ nemotronKey, setNemotronKey }}>
      {children}
    </NemotronKeyContext.Provider>
  )
}

export function useNemotronKey() {
  const ctx = useContext(NemotronKeyContext)
  if (!ctx) throw new Error('useNemotronKey must be used within a NemotronKeyProvider')
  return ctx
}
