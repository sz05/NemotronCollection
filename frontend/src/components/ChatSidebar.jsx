import { useAuth } from '../context/AuthContext'

// Sidebar listing the user's chats (newest first) with a "New chat" button.
// The list itself lives in App state so a first message can retitle the
// active chat without this component owning any fetching.
function ChatSidebar({ sessions, activeSessionId, onSelect, onNewChat }) {
  const { user, logout } = useAuth()

  return (
    <nav className="chat-sidebar">
      <button className="new-chat-button" onClick={onNewChat}>
        + New chat
      </button>
      <ul className="chat-list">
        {sessions.map((s) => (
          <li key={s.id}>
            <button
              className={`chat-list-item${s.id === activeSessionId ? ' chat-list-item--active' : ''}`}
              onClick={() => onSelect(s.id)}
              title={s.title}
            >
              {s.title}
            </button>
          </li>
        ))}
        {sessions.length === 0 && <li className="chat-list-empty">No chats yet</li>}
      </ul>
      <div className="sidebar-user">
        {user?.picture && <img src={user.picture} alt="" referrerPolicy="no-referrer" />}
        <span className="sidebar-user-name" title={user?.email}>
          {user?.name || user?.email}
        </span>
        <button className="logout-button" onClick={logout}>
          Log out
        </button>
      </div>
    </nav>
  )
}

export default ChatSidebar
