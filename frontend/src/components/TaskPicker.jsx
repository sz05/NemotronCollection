import { useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  List,
  ListItemButton,
  ListItemText,
  Stack,
  Typography,
} from '@mui/material'
import { api } from '../api/client'

// Dialog shown by the App new-chat flow: the user either locks a task/theme to
// the chat (createSession(taskId) -- the relevance guardrail then runs against
// it) or picks "Just talk" for a task-less session (taskId=null, no guardrail).
// Both are scored; only a locked task is eligible for the completion bonus.
function TaskPicker({ open, onClose, onPick, usedTaskIds = [], dismissable = true }) {
  const usedIds = new Set(usedTaskIds)
  const [tasks, setTasks] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!open) return
    setLoading(true)
    setError(null)
    setSelectedId(null)
    api
      .getTasks()
      .then((list) => setTasks(Array.isArray(list) ? list : []))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [open])

  function handleStart() {
    onPick?.(selectedId)
  }

  return (
    <Dialog
      open={open}
      onClose={(_e, _reason) => dismissable && onClose?.()}
      disableEscapeKeyDown={!dismissable}
      fullWidth
      maxWidth="sm"
    >
      <DialogTitle>
        {dismissable ? 'Start a new chat' : 'Pick a task to start'}
      </DialogTitle>
      <DialogContent dividers>
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
        {loading && <Typography color="text.secondary">Loading tasks...</Typography>}
        {!loading && (
          <List disablePadding>
            <ListItemButton
              selected={selectedId === null}
              onClick={() => setSelectedId(null)}
            >
              <ListItemText
                primary="Just talk about something random"
                secondary="Still scored, but no task locked — pick a task instead to earn a completion bonus"
              />
            </ListItemButton>
            {tasks.map((t) => {
              const taken = usedIds.has(t.id)
              return (
                <ListItemButton
                  key={t.id}
                  selected={selectedId === t.id}
                  disabled={taken}
                  onClick={() => setSelectedId(t.id)}
                >
                  <ListItemText
                    primary={
                      <Stack direction="row" spacing={1} alignItems="center">
                        <span>{t.title}</span>
                        <Chip size="small" label={t.difficulty} />
                        <Chip size="small" variant="outlined" label={`${t.base_points} pts`} />
                        {taken && <Chip size="small" color="default" label="In use" />}
                      </Stack>
                    }
                    secondary={taken ? 'Already locked to one of your chats' : t.description}
                  />
                </ListItemButton>
              )
            })}
            {tasks.length === 0 && (
              <Typography color="text.secondary" sx={{ px: 2, py: 1 }}>
                No active tasks available.
              </Typography>
            )}
          </List>
        )}
      </DialogContent>
      <DialogActions>
        {dismissable && <Button onClick={onClose}>Cancel</Button>}
        <Button variant="contained" onClick={handleStart} disabled={loading}>
          Start chat
        </Button>
      </DialogActions>
    </Dialog>
  )
}

export default TaskPicker
