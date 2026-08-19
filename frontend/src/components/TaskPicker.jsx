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

// Dialog shown by the App new-chat flow: the user picks an active task
// before a session is created (createSession(taskId)). Picking "No task /
// free chat" creates a task-less session (taskId=null).
function TaskPicker({ open, onClose, onPick }) {
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
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Start a new chat</DialogTitle>
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
                primary="No task / free chat"
                secondary="Chat without a scored task"
              />
            </ListItemButton>
            {tasks.map((t) => (
              <ListItemButton
                key={t.id}
                selected={selectedId === t.id}
                onClick={() => setSelectedId(t.id)}
              >
                <ListItemText
                  primary={
                    <Stack direction="row" spacing={1} alignItems="center">
                      <span>{t.title}</span>
                      <Chip size="small" label={t.difficulty} />
                      <Chip size="small" variant="outlined" label={`${t.base_points} pts`} />
                    </Stack>
                  }
                  secondary={t.description}
                />
              </ListItemButton>
            ))}
            {tasks.length === 0 && (
              <Typography color="text.secondary" sx={{ px: 2, py: 1 }}>
                No active tasks available.
              </Typography>
            )}
          </List>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={handleStart} disabled={loading}>
          Start chat
        </Button>
      </DialogActions>
    </Dialog>
  )
}

export default TaskPicker
