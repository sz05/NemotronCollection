import { useEffect, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Checkbox,
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
import { api } from '../api/client'

// The three anti-fraud statements the user must acknowledge before submitting.
const WARNINGS = [
  'I confirm this proof is my own genuine work and has not been submitted before.',
  'I understand that fabricated, duplicated, or plagiarised proof may lead to disqualification.',
  'I consent to my submission being reviewed and verified by a human reviewer.',
]

// Two-step proof submission dialog: an anti-fraud warning screen (3 statements
// + a required acknowledgment checkbox) followed by an upload form (a file OR a
// URL). Submits via api.submitProof with warning_ack=true.
function ProofModal({ open, sessionId, onClose, onSubmitted }) {
  const [ack, setAck] = useState(false)
  const [proofType, setProofType] = useState('file')
  const [file, setFile] = useState(null)
  const [url, setUrl] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)
  const [done, setDone] = useState(false)

  useEffect(() => {
    if (open) {
      setAck(false)
      setProofType('file')
      setFile(null)
      setUrl('')
      setError(null)
      setDone(false)
      setSubmitting(false)
    }
  }, [open])

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
      setDone(true)
      onSubmitted?.()
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Submit proof</DialogTitle>
      <DialogContent dividers>
        {done ? (
          <Alert severity="success">
            Proof submitted. It is now pending review.
          </Alert>
        ) : (
          <Stack spacing={2}>
            <Box>
              <Typography variant="subtitle2" gutterBottom>
                Before you submit, please confirm:
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
                control={
                  <Checkbox checked={ack} onChange={(e) => setAck(e.target.checked)} />
                }
                label="I acknowledge all of the statements above."
              />
            </Box>

            <Divider />

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
                <Button variant="outlined" component="label" disabled={!ack}>
                  {file ? file.name : 'Choose file'}
                  <input
                    type="file"
                    hidden
                    onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                  />
                </Button>
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
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{done ? 'Close' : 'Cancel'}</Button>
        {!done && (
          <Button variant="contained" onClick={handleSubmit} disabled={!canSubmit}>
            {submitting ? 'Submitting...' : 'Submit proof'}
          </Button>
        )}
      </DialogActions>
    </Dialog>
  )
}

export default ProofModal
