import { useCallback, useEffect, useRef, useState } from "react";
import { Box, Button, Stack } from "@mui/material";
import { api } from "./api/client";
import AdminPanel from "./components/AdminPanel";
import ApiKeyModal from "./components/ApiKeyModal";
import ChatSidebar from "./components/ChatSidebar";
import ChatView from "./components/ChatView";
import FeedbackPanel from "./components/FeedbackPanel";
import LeaderboardModal from "./components/LeaderboardModal";
import LoginScreen from "./components/LoginScreen";
import ProofModal from "./components/ProofModal";
import ScorePanel from "./components/ScorePanel";
import TaskPicker from "./components/TaskPicker";
import { useAuth } from "./context/AuthContext";
import "./App.css";

function App() {
  const { user } = useAuth();
  const [backendStatus, setBackendStatus] = useState("checking...");
  const [sessions, setSessions] = useState([]);
  const [activeSessionId, setActiveSessionId] = useState(null);
  // True while a feedback question is awaiting an answer; blocks the chat
  // input (backend enforces the same rule with a 409 on /chat).
  const [feedbackPending, setFeedbackPending] = useState(false);
  const [taskPickerOpen, setTaskPickerOpen] = useState(false);
  const [leaderboardOpen, setLeaderboardOpen] = useState(false);
  const [proofOpen, setProofOpen] = useState(false);
  const [adminOpen, setAdminOpen] = useState(false);
  const [apiKeyOpen, setApiKeyOpen] = useState(false);
  const scorePanelRef = useRef(null);

  useEffect(() => {
    api
      .health()
      .then((data) => setBackendStatus(data.status ?? "unknown"))
      .catch(() => setBackendStatus("unreachable"));
  }, []);

  const refreshSessions = useCallback(() => {
    return api.listSessions().then(setSessions);
  }, []);

  // On login: load the user's chats and open the most recent one (or a
  // fresh session if they have none yet).
  useEffect(() => {
    if (!user) {
      setSessions([]);
      setActiveSessionId(null);
      return;
    }
    api.listSessions().then((list) => {
      setSessions(list);
      if (list.length > 0) {
        setActiveSessionId(list[0].id);
      } else {
        // First-time user with no chats yet: prompt for a task instead of
        // silently creating an unscoped chat, so the very first chat is
        // task-scoped like every subsequent one (created via handlePickTask).
        setTaskPickerOpen(true);
      }
    });
  }, [user, refreshSessions]);

  // New-chat flow: pick a task first, then create the session for it.
  function handleNewChat() {
    setTaskPickerOpen(true);
  }

  async function handlePickTask(taskId) {
    try {
      const data = await api.createSession(taskId);
      setTaskPickerOpen(false);
      setActiveSessionId(data.id);
      setFeedbackPending(false);
      await refreshSessions();
    } catch (err) {
      // 409: the task was already locked to another chat (e.g. opened in a
      // second tab). Refresh so the picker greys it out; keep the dialog open.
      if (err.status === 409) await refreshSessions();
      else throw err;
    }
  }

  // Tasks the user has already locked to a chat -- greyed out in the picker so
  // the same task can't be taken twice.
  const usedTaskIds = sessions.map((s) => s.task_id).filter(Boolean);

  function handleSelect(sessionId) {
    setActiveSessionId(sessionId);
    setFeedbackPending(false);
  }

  if (user === undefined) return null; // auth state still loading
  if (user === null) return <LoginScreen />;

  return (
    <div className="app-shell">
      <ApiKeyModal open={apiKeyOpen} onClose={() => setApiKeyOpen(false)} />
      <ChatSidebar
        sessions={sessions}
        activeSessionId={activeSessionId}
        onSelect={handleSelect}
        onNewChat={handleNewChat}
      />
      <div className="app-main">
        <header className="app-header">
          <div className="app-brand">
            <span className="app-logo">N</span>
            <h1 className="app-title">Nemotron Harness</h1>
          </div>
          <Stack direction="row" spacing={1} alignItems="center">
            {user.is_admin && (
              <Button size="small" variant="text" onClick={() => setAdminOpen(true)}>
                Admin
              </Button>
            )}
            <Button size="small" variant="text" onClick={() => setApiKeyOpen(true)}>
              API key
            </Button>
            <Button size="small" variant="text" onClick={() => setLeaderboardOpen(true)}>
              Leaderboard
            </Button>
            <Button
              size="small"
              variant="contained"
              disabled={!activeSessionId}
              onClick={() => setProofOpen(true)}
            >
              Submit proof
            </Button>
            <span className={`backend-status backend-status--${backendStatus}`}>
              {backendStatus}
            </span>
          </Stack>
        </header>
        <main className="app-content">
          <ChatView
            sessionId={activeSessionId}
            feedbackPending={feedbackPending}
            onFirstMessage={refreshSessions}
            onSent={() => scorePanelRef.current?.refresh()}
          />
          <Box className="app-rail">
            <ScorePanel ref={scorePanelRef} sessionId={activeSessionId} />
            <FeedbackPanel
              sessionId={activeSessionId}
              onPendingChange={setFeedbackPending}
            />
          </Box>
        </main>
      </div>

      <TaskPicker
        open={taskPickerOpen}
        onClose={() => setTaskPickerOpen(false)}
        onPick={handlePickTask}
        usedTaskIds={usedTaskIds}
        dismissable={sessions.length > 0}
      />
      <LeaderboardModal
        open={leaderboardOpen}
        onClose={() => setLeaderboardOpen(false)}
      />
      <ProofModal
        open={proofOpen}
        sessionId={activeSessionId}
        onClose={() => setProofOpen(false)}
      />
      <AdminPanel open={adminOpen} onExit={() => setAdminOpen(false)} />
    </div>
  );
}

export default App;
