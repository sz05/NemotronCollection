import { useCallback, useEffect, useRef, useState } from "react";
import { Box, Button, Stack } from "@mui/material";
import { api } from "./api/client";
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
        api.createSession().then((data) => {
          setActiveSessionId(data.id);
          return refreshSessions();
        });
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
      <ApiKeyModal />
      <header className="app-header">
        <h1>Nemotron Harness</h1>
        <Stack direction="row" spacing={1} alignItems="center">
          <Button size="small" onClick={() => setLeaderboardOpen(true)}>
            Leaderboard
          </Button>
          <Button
            size="small"
            variant="outlined"
            disabled={!activeSessionId}
            onClick={() => setProofOpen(true)}
          >
            Submit proof
          </Button>
          <span className={`backend-status backend-status--${backendStatus}`}>
            backend: {backendStatus}
          </span>
        </Stack>
      </header>
      <main className="app-layout app-layout--with-sidebar">
        <ChatSidebar
          sessions={sessions}
          activeSessionId={activeSessionId}
          onSelect={handleSelect}
          onNewChat={handleNewChat}
        />
        <ChatView
          sessionId={activeSessionId}
          feedbackPending={feedbackPending}
          onFirstMessage={refreshSessions}
          onSent={() => scorePanelRef.current?.refresh()}
        />
        <Box sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <ScorePanel ref={scorePanelRef} sessionId={activeSessionId} />
          <FeedbackPanel
            sessionId={activeSessionId}
            onPendingChange={setFeedbackPending}
          />
        </Box>
      </main>

      <TaskPicker
        open={taskPickerOpen}
        onClose={() => setTaskPickerOpen(false)}
        onPick={handlePickTask}
        usedTaskIds={usedTaskIds}
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
    </div>
  );
}

export default App;
