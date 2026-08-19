import { useCallback, useEffect, useImperativeHandle, forwardRef, useState } from 'react'
import { Box, LinearProgress, Paper, Stack, Typography } from '@mui/material'
import { api } from '../api/client'

const COMPONENT_LABELS = {
  responsiveness: 'Responsiveness',
  elaboration: 'Elaboration',
  development: 'Development',
  progress: 'Progress',
}

// Live score panel: shows the session live_score plus the R/E/D/P breakdown.
// Fetches api.getScore(sessionId) on session change; the parent can trigger a
// refetch after each sent message via the imperative `refresh()` handle.
const ScorePanel = forwardRef(function ScorePanel({ sessionId }, ref) {
  const [score, setScore] = useState(null)
  const [error, setError] = useState(null)

  const load = useCallback(() => {
    if (!sessionId) {
      setScore(null)
      return
    }
    api
      .getScore(sessionId)
      .then((data) => {
        setScore(data)
        setError(null)
      })
      .catch((err) => setError(err.message))
  }, [sessionId])

  useEffect(() => {
    load()
  }, [load])

  useImperativeHandle(ref, () => ({ refresh: load }), [load])

  if (!sessionId) return null

  const live = Math.max(0, Math.min(100, score?.live_score ?? 0))
  const components = score?.components ?? {}

  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Typography variant="subtitle1" gutterBottom>
        Live score
      </Typography>
      {error && (
        <Typography variant="body2" color="error">
          {error}
        </Typography>
      )}
      <Box sx={{ mb: 2 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="baseline">
          <Typography variant="h5">{Math.round(live)}</Typography>
          <Typography variant="caption" color="text.secondary">
            / 100
          </Typography>
        </Stack>
        <LinearProgress variant="determinate" value={live} sx={{ mt: 0.5, height: 8, borderRadius: 4 }} />
      </Box>
      <Stack spacing={1.25}>
        {Object.entries(COMPONENT_LABELS).map(([key, label]) => {
          const val = Math.max(0, Math.min(100, Number(components[key] ?? 0)))
          return (
            <Box key={key}>
              <Stack direction="row" justifyContent="space-between">
                <Typography variant="caption" color="text.secondary">
                  {label}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {Math.round(val)}
                </Typography>
              </Stack>
              <LinearProgress
                variant="determinate"
                value={val}
                color="secondary"
                sx={{ mt: 0.25, height: 6, borderRadius: 3 }}
              />
            </Box>
          )
        })}
      </Stack>
    </Paper>
  )
})

export default ScorePanel
