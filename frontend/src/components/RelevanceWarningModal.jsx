import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
} from '@mui/material'

// Shown when a /chat response comes back with a relevance_warning (the message
// looked off-topic for the task). "Yes, continue" resends the same message with
// acknowledgeOfftopic=true; "No, go back" restores the draft so the user can
// edit it. `warning` is the { score, message } object from the response.
function RelevanceWarningModal({ open, warning, onContinue, onCancel }) {
  return (
    <Dialog open={open} onClose={onCancel} maxWidth="sm" fullWidth>
      <DialogTitle>This looks off-topic</DialogTitle>
      <DialogContent>
        <DialogContentText>
          {warning?.message ||
            'Your message may not be relevant to the current task. Do you want to send it anyway?'}
        </DialogContentText>
        {typeof warning?.score === 'number' && (
          <DialogContentText sx={{ mt: 1, fontSize: '0.85rem' }} color="text.secondary">
            Relevance score: {warning.score.toFixed(2)}
          </DialogContentText>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onCancel}>No, go back</Button>
        <Button variant="contained" onClick={onContinue}>
          Yes, continue
        </Button>
      </DialogActions>
    </Dialog>
  )
}

export default RelevanceWarningModal
