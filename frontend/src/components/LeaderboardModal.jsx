import { useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material'
import { api } from '../api/client'

// Non-blocking leaderboard dialog. Fetches api.getLeaderboard() when opened and
// highlights the caller's own row (response.me). Ranked, points, tasks
// completed, and average live score per user.
function LeaderboardModal({ open, onClose }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!open) return
    setLoading(true)
    setError(null)
    api
      .getLeaderboard()
      .then(setData)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [open])

  const entries = data?.entries ?? []
  const meId = data?.me?.user_id ?? null

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="md">
      <DialogTitle>Leaderboard</DialogTitle>
      <DialogContent dividers>
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
        {loading && <Typography color="text.secondary">Loading...</Typography>}
        {!loading && (
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>#</TableCell>
                  <TableCell>Player</TableCell>
                  <TableCell align="right">Points</TableCell>
                  <TableCell align="right">Tasks</TableCell>
                  <TableCell align="right">Avg live score</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {entries.map((e) => {
                  const isMe = meId && e.user_id === meId
                  return (
                    <TableRow
                      key={e.user_id}
                      sx={isMe ? { bgcolor: 'action.selected' } : undefined}
                    >
                      <TableCell>{e.rank}</TableCell>
                      <TableCell>
                        {e.display_name || 'Anonymous'}
                        {isMe ? ' (you)' : ''}
                      </TableCell>
                      <TableCell align="right">{e.total_points}</TableCell>
                      <TableCell align="right">{e.tasks_completed}</TableCell>
                      <TableCell align="right">
                        {Number(e.avg_live_score ?? 0).toFixed(1)}
                      </TableCell>
                    </TableRow>
                  )
                })}
                {entries.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={5}>
                      <Typography color="text.secondary">No entries yet.</Typography>
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  )
}

export default LeaderboardModal
