import { useCallback, useEffect, useImperativeHandle, forwardRef, useState } from 'react'
import { Box, Paper, Typography } from '@mui/material'
import { api, WS_BASE_URL } from '../api/client'

// Total score panel: shows the user's cumulative score summed across ALL of
// their chats (GET /score/total), not just the open one. Each chat's own
// live_score grows every few turns; the total is the sum of them all.
//
// Kept live without a reload: the active chat's socket
// (/ws/feedback/{sessionId}) pushes a {type:'score'} frame whenever that chat
// re-scores, and we re-fetch the total in response (the pushed value is only
// one chat's contribution, so a refetch is the correct way to fold it into the
// cross-chat sum). We also refetch on session switch and via refresh().
const ScorePanel = forwardRef(function ScorePanel({ sessionId }, ref) {
  const [total, setTotal] = useState(null)
  const [error, setError] = useState(null)

  const loadTotal = useCallback(() => {
    api
      .getTotalScore()
      .then((data) => {
        setTotal(Number(data.total_score ?? 0))
        setError(null)
      })
      .catch((err) => setError(err.message))
  }, [])

  // Refetch on mount and whenever the active chat changes.
  useEffect(() => {
    loadTotal()
  }, [loadTotal, sessionId])

  useImperativeHandle(ref, () => ({ refresh: loadTotal }), [loadTotal])

  // Live push over the active chat's feedback socket. Score frames are
  // {type:'score'}; on one, refetch the cross-chat total.
  useEffect(() => {
    if (!sessionId) return
    const ws = new WebSocket(`${WS_BASE_URL}/ws/feedback/${sessionId}`)
    ws.onmessage = (event) => {
      let data
      try {
        data = JSON.parse(event.data)
      } catch {
        return
      }
      if (data.type === 'score') {
        loadTotal()
      }
    }
    return () => ws.close()
  }, [sessionId, loadTotal])

  if (total === null) return null

  const shown = Math.max(0, Math.round(total))

  return (
    <Paper variant="outlined" sx={{ p: 2.25, borderRadius: 2 }}>
      <Typography
        variant="overline"
        sx={{ color: 'text.secondary', letterSpacing: '0.08em', fontWeight: 600 }}
      >
        Total score
      </Typography>
      {error && (
        <Typography variant="body2" color="error">
          {error}
        </Typography>
      )}
      <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 0.75, mt: 0.25 }}>
        <Typography sx={{ fontSize: '2.4rem', lineHeight: 1, fontWeight: 700, letterSpacing: '-0.02em' }}>
          {shown}
        </Typography>
        <Typography variant="body2" sx={{ color: 'text.secondary' }}>
          pts
        </Typography>
      </Box>
      <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block', mt: 0.5 }}>
        Across all your chats · updates every few turns
      </Typography>
      <Box sx={{ mt: 1.5, pt: 1.5, borderTop: '1px solid', borderColor: 'divider' }}>
        <Typography variant="caption" sx={{ color: 'text.secondary' }}>
          Complete a task and submit proof for bonus points.
        </Typography>
      </Box>
    </Paper>
  )
})

export default ScorePanel
