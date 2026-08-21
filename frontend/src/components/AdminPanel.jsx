import { useEffect, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  MenuItem,
  Stack,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tabs,
  TextField,
  Typography,
} from '@mui/material'
import { api } from '../api/client'

// Admin console as a full-screen page (only mounted for allowlisted admins).
// Scoring is now automatic (Gemini scores each submitted chat), so there's no
// manual proof-review queue. Two tabs remain:
//  - Leaderboard: live totals.
//  - Add task: create a new challenge/theme.
function AdminPanel({ open, onExit }) {
  const [tab, setTab] = useState(0)

  if (!open) return null

  return (
    <Box
      sx={{
        position: 'fixed',
        inset: 0,
        zIndex: 1300,
        bgcolor: 'background.default',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <Box
        sx={{
          height: 57,
          px: 2.5,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          borderBottom: '1px solid',
          borderColor: 'divider',
          flexShrink: 0,
        }}
      >
        <Stack direction="row" spacing={1.5} alignItems="center">
          <Box
            sx={{
              width: 26,
              height: 26,
              borderRadius: 1.5,
              bgcolor: 'primary.main',
              color: '#fff',
              display: 'grid',
              placeItems: 'center',
              fontSize: 13,
              fontWeight: 700,
            }}
          >
            N
          </Box>
          <Typography sx={{ fontWeight: 600 }}>Admin console</Typography>
        </Stack>
        <Button size="small" variant="outlined" onClick={onExit}>
          ← Back to app
        </Button>
      </Box>

      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ px: 2.5, borderBottom: '1px solid', borderColor: 'divider', flexShrink: 0 }}>
        <Tab label="Leaderboard" />
        <Tab label="Add task" />
      </Tabs>

      <Box sx={{ flex: 1, overflowY: 'auto', p: 3 }}>
        <Box sx={{ maxWidth: 960, mx: 'auto' }}>
          {tab === 0 && <Leaderboard open={open} />}
          {tab === 1 && <AddTask />}
        </Box>
      </Box>
    </Box>
  )
}

function Leaderboard({ open }) {
  const [rows, setRows] = useState([])
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!open) return
    api
      .getLeaderboard()
      .then((d) => setRows(d.entries ?? []))
      .catch((err) => setError(err.message))
  }, [open])

  return (
    <>
      {error && <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert>}
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>#</TableCell>
            <TableCell>Player</TableCell>
            <TableCell align="right">Total score</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((e) => (
            <TableRow key={e.user_id}>
              <TableCell>{e.rank}</TableCell>
              <TableCell>{e.display_name || 'Anonymous'}</TableCell>
              <TableCell align="right">{e.total_points}</TableCell>
            </TableRow>
          ))}
          {rows.length === 0 && (
            <TableRow>
              <TableCell colSpan={3}>
                <Typography color="text.secondary">No entries yet.</Typography>
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </>
  )
}

function AddTask() {
  const [form, setForm] = useState({
    title: '',
    description: '',
    difficulty: 'medium',
    base_points: 150,
    instructions: '',
    proof_types: ['url', 'file', 'image'],
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [ok, setOk] = useState(false)

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  async function submit() {
    setBusy(true)
    setError(null)
    setOk(false)
    try {
      await api.createTask({ ...form, base_points: Number(form.base_points) })
      setOk(true)
      setForm((f) => ({ ...f, title: '', description: '', instructions: '' }))
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Stack spacing={2} sx={{ maxWidth: 560 }}>
      {ok && <Alert severity="success">Task created.</Alert>}
      {error && <Alert severity="error">{error}</Alert>}
      <TextField label="Title" value={form.title} onChange={set('title')} fullWidth />
      <TextField
        label="Description"
        value={form.description}
        onChange={set('description')}
        fullWidth
        multiline
        minRows={3}
      />
      <Stack direction="row" spacing={2}>
        <TextField select label="Difficulty" value={form.difficulty} onChange={set('difficulty')} sx={{ width: 160 }}>
          <MenuItem value="easy">easy</MenuItem>
          <MenuItem value="medium">medium</MenuItem>
          <MenuItem value="hard">hard</MenuItem>
        </TextField>
        <TextField
          label="Base points"
          type="number"
          value={form.base_points}
          onChange={set('base_points')}
          sx={{ width: 160 }}
        />
      </Stack>
      <TextField
        label="Instructions (optional)"
        value={form.instructions}
        onChange={set('instructions')}
        fullWidth
      />
      <Button variant="contained" onClick={submit} disabled={busy || !form.title.trim()}>
        {busy ? 'Creating…' : 'Create task'}
      </Button>
    </Stack>
  )
}

export default AdminPanel
