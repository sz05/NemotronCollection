import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControlLabel,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { api, WS_BASE_URL } from '../api/client'

// The three anti-fraud statements the user must acknowledge before submitting.
const WARNINGS = [
  'I confirm this proof is my own genuine work and has not been submitted before.',
  'I understand that fabricated, duplicated, or plagiarised proof may lead to disqualification.',
  'I consent to my submission being reviewed and verified by a human reviewer.',
]

const STATUS_COLOR = { pending: 'warning', verified: 'success', rejected: 'error' }

// Proof submission dialog. Shows the participant's existing submissions with the
// grade (%/points) an admin gave, and lets them submit a *better* proof to earn
// more points -- re-grading a stronger PoC raises their award.
function ProofModal({ open, sessionId, onClose, onSubmitted }) {
  const [ack, setAck] = useState(false)
  const [proofType, setProofType] = useState('file')
  const [file, setFile] = useState(null)
  const [url, setUrl] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)
  const [justSubmitted, setJustSubmitted] = useState(false)
  const [submissions, setSubmissions] = useState([])

  const loadSubmissions = useCallback(() => {
    if (!sessionId) return
    api
      .getProofStatus(sessionId)
      .then(setSubmissions)
      .catch(() => setSubmissions([]))
  }, [sessionId])

  useEffect(() => {
    if (open) {
      setAck(false)
      setProofType('file')
      setFile(null)
      setUrl('')
      setError(null)
      setJustSubmitted(false)
      setSubmitting(false)
      loadSubmissions()
    }
  }, [open, loadSubmissions])

  // While open, refresh the submissions list when the backend signals a change
  // over the session socket (the admin's grade/reject pushes a score frame), so
  // "Awaiting review" flips to the result without a reload.
  useEffect(() => {
    if (!open || !sessionId) return
    const ws = new WebSocket(`${WS_BASE_URL}/ws/feedback/${sessionId}`)
    ws.onmessage = (event) => {
      let data
      try {
        data = JSON.parse(event.data)
      } catch {
        return
      }
      if (data.type === 'score') loadSubmissions()
    }
    return () => ws.close()
  }, [open, sessionId, loadSubmissions])

  const canSubmit =
    ack && !submitting && (proofType === 'file' ? Boolean(file) : Boolean(url.trim()))

  async function handleSubmit() {
    if (!canSubmit || !sessionId) return
    setSubmitting(true)
    setError(null)
    const fd = new FormData()
    fd.append('proof_type', proofType)
    fd.append('warning_ack', 'true')
    if (proofType === 'file' && file) fd.append('file', file)
    if (proofType === 'url') fd.append('url', url.trim())
    try {
      await api.submitProof(sessionId, fd)
      setJustSubmitted(true)
      setAck(false)
      setFile(null)
      setUrl('')
      loadSubmissions()
      onSubmitted?.()
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  const hasSubmissions = submissions.length > 0

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Proof of completion</DialogTitle>
      <DialogContent dividers>
        <Stack spacing={2}>
          {hasSubmissions && (
            <Box>
              <Typography variant="subtitle2" gutterBottom>
                Your submissions
              </Typography>
              <Stack spacing={1}>
                {submissions.map((s) => (
                  <Box
                    key={s.id}
                    sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 2, p: 1.25 }}
                  >
                    <Stack direction="row" spacing={1} alignItems="center" sx={{ flexWrap: 'wrap' }}>
                      <Chip size="small" label={s.status} color={STATUS_COLOR[s.status] || 'default'} />
                      {s.status === 'verified' ? (
                        <Typography variant="body2">
                          Graded <strong>{s.percent}%</strong> · {s.points} pts
                        </Typography>
                      ) : s.status === 'rejected' ? (
                        <Typography variant="body2" color="text.secondary">
                          Rejected — no points awarded
                        </Typography>
                      ) : (
                        <Typography variant="body2" color="text.secondary">
                          Awaiting review
                        </Typography>
                      )}
                    </Stack>
                    {s.review_notes && (
                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                        Reviewer: {s.review_notes}
                      </Typography>
                    )}
                  </Box>
                ))}
              </Stack>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
                Not happy with your score? Submit a stronger proof below — a better
                PoC can earn you more points.
              </Typography>
              <Divider sx={{ mt: 1.5 }} />
            </Box>
          )}

          {justSubmitted && (
            <Alert severity="success">Proof submitted — it's now pending review.</Alert>
          )}

          <Box>
            <Typography variant="subtitle2" gutterBottom>
              {hasSubmissions ? 'Submit a better proof' : 'Before you submit, please confirm:'}
            </Typography>
            <Stack spacing={0.5}>
              {WARNINGS.map((w) => (
                <Typography key={w} variant="body2" color="text.secondary">
                  • {w}
                </Typography>
              ))}
            </Stack>
            <FormControlLabel
              sx={{ mt: 1 }}
              control={<Checkbox checked={ack} onChange={(e) => setAck(e.target.checked)} />}
              label="I acknowledge all of the statements above."
            />
          </Box>

          <Box>
            <Stack direction="row" spacing={1} sx={{ mb: 2 }}>
              <Button
                size="small"
                variant={proofType === 'file' ? 'contained' : 'outlined'}
                onClick={() => setProofType('file')}
              >
                Upload file
              </Button>
              <Button
                size="small"
                variant={proofType === 'url' ? 'contained' : 'outlined'}
                onClick={() => setProofType('url')}
              >
                Provide URL
              </Button>
            </Stack>

            {proofType === 'file' ? (
              <Box>
                <Button variant="outlined" component="label" disabled={!ack}>
                  {file ? file.name : 'Choose file'}
                  <input type="file" hidden onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
                </Button>
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                  PNG, JPG, GIF, WEBP or PDF · up to 15 MB. For repos or live sites, use a URL.
                </Typography>
              </Box>
            ) : (
              <TextField
                fullWidth
                label="Proof URL"
                placeholder="https://..."
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                disabled={!ack}
              />
            )}
          </Box>

          {error && <Alert severity="error">{error}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Close</Button>
        <Button variant="contained" onClick={handleSubmit} disabled={!canSubmit}>
          {submitting ? 'Submitting...' : 'Submit proof'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

export default ProofModal
