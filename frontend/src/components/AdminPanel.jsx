import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Chip,
  Divider,
  Link,
  MenuItem,
  Slider,
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

const STATUS_COLOR = { pending: 'warning', verified: 'success', rejected: 'error' }

// Admin console as a full-screen page (only mounted for allowlisted admins).
// Three tabs:
//  - Submissions: every participant PoC, with a % slider to award points,
//    plus reject. Re-grading a resubmitted PoC raises their points.
//  - Leaderboard: live totals.
//  - Add task: create a new challenge.
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
        <Tab label="Submissions" />
        <Tab label="Leaderboard" />
        <Tab label="Add task" />
      </Tabs>

      <Box sx={{ flex: 1, overflowY: 'auto', p: 3 }}>
        <Box sx={{ maxWidth: 960, mx: 'auto' }}>
          {tab === 0 && <Submissions open={open} />}
          {tab === 1 && <Leaderboard open={open} />}
          {tab === 2 && <AddTask open={open} />}
        </Box>
      </Box>
    </Box>
  )
}

function Submissions({ open }) {
  const [proofs, setProofs] = useState([])
  const [pct, setPct] = useState({}) // proofId -> slider percent
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    api
      .adminListProofs()
      .then((list) => {
        setProofs(list)
        setPct((prev) => {
          const next = { ...prev }
          for (const p of list) if (next[p.id] === undefined) next[p.id] = p.percent ?? 100
          return next
        })
        setError(null)
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (open) load()
  }, [open, load])

  async function grade(proof, decision) {
    setBusy(proof.id)
    setError(null)
    try {
      await api.adminReview(proof.id, {
        decision,
        qualityFactor: (pct[proof.id] ?? 100) / 100,
      })
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(null)
    }
  }

  async function viewFile(proofId) {
    try {
      const url = await api.adminProofFileUrl(proofId)
      window.open(url, '_blank', 'noopener')
    } catch (err) {
      setError(err.message)
    }
  }

  if (loading && proofs.length === 0) return <Typography color="text.secondary">Loading…</Typography>

  return (
    <Stack spacing={1.5}>
      {error && <Alert severity="error">{error}</Alert>}
      {proofs.length === 0 && <Typography color="text.secondary">No submissions yet.</Typography>}
      {proofs.map((p) => (
        <Box key={p.id} sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 2, p: 1.5 }}>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ flexWrap: 'wrap' }}>
            <Typography sx={{ fontWeight: 600 }}>{p.user_name || p.user_email}</Typography>
            <Typography variant="body2" color="text.secondary">
              {p.user_email}
            </Typography>
            <Chip size="small" label={p.status} color={STATUS_COLOR[p.status] || 'default'} />
            {p.percent != null && (
              <Chip size="small" variant="outlined" label={`${p.percent}% · ${p.points} pts`} />
            )}
          </Stack>
          <Typography variant="body2" sx={{ mt: 0.5 }}>
            Task: {p.task_title}{' '}
            <Typography component="span" variant="caption" color="text.secondary">
              (base {p.base_points} pts)
            </Typography>
          </Typography>

          <Stack direction="row" spacing={2} alignItems="center" sx={{ mt: 0.75 }}>
            {p.has_file && (
              <Button size="small" variant="outlined" onClick={() => viewFile(p.id)}>
                View file
              </Button>
            )}
            {p.url && (
              // Show the full URL as inspectable text (not a bare "Open link"
              // button) so the reviewer can see where a participant-supplied
              // link goes before clicking it.
              <Link
                href={p.url}
                target="_blank"
                rel="noopener noreferrer"
                variant="body2"
                title={p.url}
                sx={{ wordBreak: 'break-all' }}
              >
                {p.url} ↗
              </Link>
            )}
          </Stack>

          <Divider sx={{ my: 1 }} />
          <Stack direction="row" spacing={2} alignItems="center">
            <Box sx={{ flex: 1, minWidth: 160 }}>
              <Typography variant="caption" color="text.secondary">
                Award: {pct[p.id] ?? 100}% of points
              </Typography>
              <Slider
                size="small"
                value={pct[p.id] ?? 100}
                onChange={(_, v) => setPct((s) => ({ ...s, [p.id]: v }))}
                valueLabelDisplay="auto"
                min={0}
                max={100}
              />
            </Box>
            <Button
              size="small"
              variant="contained"
              disabled={busy === p.id}
              onClick={() => grade(p, 'verified')}
            >
              {p.status === 'verified' ? 'Re-grade' : 'Verify & award'}
            </Button>
            {/* Reject only from the pending state. Once a proof is graded,
                rejecting it would strand the awarded points (the reject path
                doesn't remove the award), so a graded proof can only be
                re-graded; a rejected one can still be verified to award score. */}
            {p.status === 'pending' && (
              <Button
                size="small"
                color="error"
                variant="outlined"
                disabled={busy === p.id}
                onClick={() => grade(p, 'rejected')}
              >
                Reject
              </Button>
            )}
          </Stack>
        </Box>
      ))}
    </Stack>
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
        label="Instructions (what proof to submit)"
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
