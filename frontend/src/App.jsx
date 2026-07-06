import React, { useState, useEffect, useRef } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { open } from '@tauri-apps/plugin-dialog';
import { listen } from '@tauri-apps/api/event';
import { MessageSquare, Video, Send, RefreshCw, AlertCircle, Plus, History, PanelLeftClose, PanelLeftOpen, Trash2 } from 'lucide-react';
import ReactMarkdown from 'react-markdown';

const STORAGE_KEY = 'offline_agent_sessions';

export default function App() {
  const [sessions, setSessions] = useState([]);
  const [activeSessionId, setActiveSessionId] = useState(null);
  const [input, setInput] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [confirmAction, setConfirmAction] = useState(null);
  const chatBottomRef = useRef(null);
  const inputRef = useRef(null);

  const activeSession = sessions.find((session) => session.id === activeSessionId) || null;
  const messages = activeSession?.messages || [];
  const activeVideoPath = activeSession?.videoPath || '';
  const activeHitlPrompt = activeSession?.hitlPrompt || null;

  const createSessionObject = (persisted = true) => ({
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    title: 'New Session',
    createdAt: new Date().toISOString(),
    messages: [],
    videoPath: '',
    hitlPrompt: null,
    isDraft: !persisted,
  });

  const sessionHasContent = (session) => Boolean(session && (session.videoPath || (session.messages && session.messages.length > 0) || session.hitlPrompt));

  const getPersistableSessions = (nextSessions) => nextSessions.filter((session) => !session.isDraft && sessionHasContent(session));

  const persistSessions = (nextSessions, nextActiveId = activeSessionId) => {
    setSessions(nextSessions);
    setActiveSessionId(nextActiveId);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(getPersistableSessions(nextSessions)));
  };

  const createNewSession = ({ persist = true, replaceExisting = false } = {}) => {
    if (!replaceExisting) {
      const existingEmptyDraft = sessions.find((session) => session.isDraft && !sessionHasContent(session));
      if (existingEmptyDraft) {
        setActiveSessionId(existingEmptyDraft.id);
        setInput('');
        return existingEmptyDraft;
      }

      const currentActiveSession = sessions.find((session) => session.id === activeSessionId);
      if (currentActiveSession && currentActiveSession.isDraft && !sessionHasContent(currentActiveSession)) {
        setInput('');
        return currentActiveSession;
      }
    }

    const session = createSessionObject(persist);

    setSessions((prevSessions) => {
      const currentSessions = Array.isArray(prevSessions) ? prevSessions : [];
      const remainingSessions = replaceExisting ? [] : currentSessions;
      const nextSessions = [session, ...remainingSessions];
      localStorage.setItem(STORAGE_KEY, JSON.stringify(getPersistableSessions(nextSessions)));
      return nextSessions;
    });
    setActiveSessionId(session.id);
    setInput('');
    return session;
  };

  const ensureActiveSession = () => {
    if (activeSessionId) return activeSession;
    return createNewSession();
  };

  const updateActiveSession = (updater, sessionId = activeSessionId) => {
    if (!sessionId) return;
    setSessions((prev) => {
      const next = prev.map((session) => (session.id === sessionId ? updater(session) : session));
      const normalized = next.map((session) => {
        if (session.id !== sessionId) return session;
        if (session.isDraft && sessionHasContent(session)) {
          return { ...session, isDraft: false };
        }
        if (!sessionHasContent(session) && !session.isDraft && sessionId === activeSessionId) {
          return { ...session, isDraft: true };
        }
        return session;
      });
      localStorage.setItem(STORAGE_KEY, JSON.stringify(getPersistableSessions(normalized)));
      return normalized;
    });
  };

  const formatSessionDate = (value) => {
    if (!value) return 'Just now';
    try {
      return new Date(value).toLocaleString([], {
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
      });
    } catch {
      return 'Just now';
    }
  };

  const getSessionPreview = (session) => {
    if (!session?.messages?.length) return 'Fresh session';
    const botMessages = [...session.messages].reverse().filter((message) => message.sender === 'bot' && message.text);
    const previewSource = botMessages.find((message) => !message.text.includes('Connecting')) || botMessages[0] || [...session.messages].reverse()[0];
    const plainText = previewSource.text
      .replace(/[#>*_`\[\]()]/g, '')
      .replace(/\s+/g, ' ')
      .trim();
    return plainText.length > 70 ? `${plainText.slice(0, 67)}...` : plainText;
  };

  const focusChatInput = () => {
    requestAnimationFrame(() => {
      if (!isProcessing && activeVideoPath && inputRef.current) {
        inputRef.current.focus();
      }
    });
  };

  useEffect(() => {
    const savedSessions = localStorage.getItem(STORAGE_KEY);
    if (savedSessions) {
      try {
        const parsed = JSON.parse(savedSessions);
        if (Array.isArray(parsed) && parsed.length > 0) {
          const sanitized = parsed.filter((session) => sessionHasContent(session));
          if (sanitized.length > 0) {
            setSessions(sanitized);
            setActiveSessionId(sanitized[0].id);
            return;
          }
        }
      } catch (error) {
        console.error('Failed to parse saved sessions', error);
      }
    }

    const legacyHistory = localStorage.getItem('offline_agent_history');
    if (legacyHistory) {
      try {
        const legacyMessages = JSON.parse(legacyHistory);
        const importedSession = {
          id: `${Date.now()}-imported`,
          title: 'Imported Session',
          createdAt: new Date().toISOString(),
          messages: legacyMessages,
          videoPath: '',
          hitlPrompt: null,
          isDraft: false,
        };
        persistSessions([importedSession]);
        localStorage.removeItem('offline_agent_history');
      } catch (error) {
        console.error('Failed to import legacy history', error);
      }
      return;
    }

    createNewSession({ persist: false });
  }, []);

  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, activeHitlPrompt]);

  useEffect(() => {
    focusChatInput();
  }, [activeSessionId, activeVideoPath, isProcessing]);

  useEffect(() => {
    if (!activeSessionId && sessions.length === 0) {
      createNewSession({ persist: false });
    }
  }, [activeSessionId, sessions.length]);

  const browseLocalVideo = async () => {
    try {
      const selected = await open({
        multiple: false,
        filters: [{ name: 'Video Format', extensions: ['mp4'] }],
      });
      if (selected) {
        const currentSessionId = activeSessionId || ensureActiveSession()?.id;
        if (!currentSessionId) return;
        updateActiveSession(
          (session) => ({
            ...session,
            videoPath: selected,
            title: session.title === 'New Session' ? selected.split(/[\\/]/).pop() : session.title,
          }),
          currentSessionId
        );
      }
    } catch (error) {
      console.error('Native File Open Cancelled/Failed:', error);
    }
  };

  const clearCurrentSession = () => {
    const currentSessionId = activeSessionId || ensureActiveSession()?.id;
    if (!currentSessionId) return;
    updateActiveSession(
      (session) => ({
        ...session,
        title: 'New Session',
        messages: [],
        videoPath: '',
        hitlPrompt: null,
        isDraft: true,
      }),
      currentSessionId
    );
    setInput('');
  };

  const requestDeleteSession = (sessionId) => {
    const targetSession = sessions.find((session) => session.id === sessionId);
    if (!targetSession) return;
    setConfirmAction({
      type: 'session',
      sessionId,
      title: targetSession.title,
      message: `Delete history for "${targetSession.title}"?`,
    });
  };

  const requestClearAllHistory = () => {
    setConfirmAction({
      type: 'all',
      title: 'Clear all history',
      message: 'This will remove all saved sessions.',
    });
  };

  const confirmActionHandler = () => {
    if (!confirmAction) return;

    if (confirmAction.type === 'session') {
      const nextSessions = sessions.filter((session) => session.id !== confirmAction.sessionId);
      const fallbackId = nextSessions[0]?.id || null;
      persistSessions(nextSessions, fallbackId);
      if (activeSessionId === confirmAction.sessionId && fallbackId) {
        setActiveSessionId(fallbackId);
      }
      if (nextSessions.length === 0) {
        createNewSession({ persist: false, replaceExisting: true });
      }
    } else {
      setSessions([]);
      localStorage.removeItem(STORAGE_KEY);
      setActiveSessionId(null);
      createNewSession({ persist: false, replaceExisting: true });
    }

    setConfirmAction(null);
  };

  const cancelConfirmAction = () => {
    setConfirmAction(null);
  };

  const transmitMessage = async (explicitQuery = null, hitlSelection = null) => {
    const activeText = explicitQuery || input;
    if (!activeText.trim() && !hitlSelection) return;

    const currentSessionId = activeSessionId || ensureActiveSession()?.id;
    if (!currentSessionId) return;

    setIsProcessing(true);
    const sessionMessages = messages || [];
    const userBubble = {
      id: Date.now(),
      sender: 'user',
      text: hitlSelection ? `[Selected Option]: ${hitlSelection}` : activeText,
      timestamp: new Date().toLocaleTimeString(),
    };

    const responseId = Date.now() + 1;
    const placeholderMessage = {
      id: responseId,
      sender: 'bot',
      text: '⏳ Connecting to local agent sub-channels...',
      timestamp: new Date().toLocaleTimeString(),
    };

    const nextMessages = [...sessionMessages, userBubble, placeholderMessage];
    updateActiveSession(
      (session) => ({
        ...session,
        title: session.messages.length === 0 ? (activeText.length > 30 ? `${activeText.slice(0, 30)}...` : activeText) : session.title,
        messages: nextMessages,
        hitlPrompt: null,
      }),
      currentSessionId
    );

    setInput('');
    let liveMessages = nextMessages;

    try {
      const unlisten = await listen('grpc-chunk-received', (event) => {
        const payload = event.payload;

        if (payload.type === 'CLARIFICATION_REQUIRED') {
          updateActiveSession(
            (session) => ({
              ...session,
              hitlPrompt: {
                text: payload.content,
                options: payload.clarification_options,
              },
              messages: liveMessages.filter((message) => message.id !== responseId),
            }),
            currentSessionId
          );
        } else if (payload.type === 'REPORT_GENERATED') {
          liveMessages = liveMessages.map((message) =>
            message.id === responseId
              ? {
                  ...message,
                  text: `${payload.content}\n\n📁 **Export Location:** [Open Document Path](${payload.file_url})`,
                }
              : message
          );
          updateActiveSession((session) => ({ ...session, messages: liveMessages }), currentSessionId);
        } else {
          liveMessages = liveMessages.map((message) =>
            message.id === responseId
              ? {
                  ...message,
                  text: message.text === '⏳ Connecting to local agent sub-channels...' ? payload.content : message.text + payload.content,
                }
              : message
          );
          updateActiveSession((session) => ({ ...session, messages: liveMessages }), currentSessionId);
        }
      });

      await invoke('route_agent_query', {
        userQuery: activeText,
        videoPath: activeVideoPath,
        isClarification: hitlSelection !== null,
        selectedOption: hitlSelection || '',
      });

      unlisten();
    } catch (error) {
      liveMessages = liveMessages.map((message) =>
        message.id === responseId ? { ...message, text: `❌ **Local Communication Error:** ${error.toString()}` } : message
      );
      updateActiveSession((session) => ({ ...session, messages: liveMessages }), currentSessionId);
    } finally {
      setIsProcessing(false);
      focusChatInput();
    }
  };

  return (
    <div className="app-container" style={styles.container}>
      {confirmAction && (
        <div style={styles.confirmOverlay} onClick={cancelConfirmAction}>
          <div style={styles.confirmDialog} onClick={(event) => event.stopPropagation()}>
            <h4 style={styles.confirmTitle}>{confirmAction.title}</h4>
            <p style={styles.confirmMessage}>{confirmAction.message}</p>
            <div style={styles.confirmActions}>
              <button onClick={cancelConfirmAction} style={styles.confirmCancelBtn}>Cancel</button>
              <button onClick={confirmActionHandler} style={styles.confirmDeleteBtn}>Delete</button>
            </div>
          </div>
        </div>
      )}
      <aside style={{ ...styles.sidebar, ...(isSidebarCollapsed ? styles.sidebarCollapsed : {}) }}>
        <div style={{ ...styles.sidebarHeader, ...(isSidebarCollapsed ? styles.sidebarHeaderCollapsed : {}) }}>
          {!isSidebarCollapsed && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <History size={18} color="#4ecdc4" />
              <h3 style={styles.sidebarTitle}>History</h3>
            </div>
          )}
          {isSidebarCollapsed ? (
            <div style={styles.collapsedActionStack}>
              <button onClick={() => setIsSidebarCollapsed(false)} style={styles.toggleSidebarBtn}>
                <PanelLeftOpen size={16} />
              </button>
              <button onClick={() => createNewSession({ persist: false })} style={styles.newSessionBtn}>
                <Plus size={16} />
              </button>
            </div>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <button onClick={() => createNewSession({ persist: false })} style={styles.newSessionBtn}>
                <Plus size={16} />
              </button>
              <button onClick={() => setIsSidebarCollapsed(true)} style={styles.toggleSidebarBtn}>
                <PanelLeftClose size={16} />
              </button>
            </div>
          )}
        </div>

        {!isSidebarCollapsed && (
          <div style={styles.sessionList}>
            <div style={styles.historyToolbar}>
              <span style={styles.historyToolbarLabel}>Recent sessions</span>
              <button onClick={requestClearAllHistory} style={styles.historyToolbarBtn}>
                <Trash2 size={14} />
              </button>
            </div>
            {sessions.filter((session) => !session.isDraft).length === 0 ? (
              <div style={styles.emptyState}>No recent sessions yet.</div>
            ) : (
              sessions.filter((session) => !session.isDraft).map((session) => (
                <div key={session.id} style={styles.sessionCard}>
                  <button
                    onClick={() => {
                      setActiveSessionId(session.id);
                      setInput('');
                    }}
                    style={{
                      ...styles.sessionButton,
                      ...(activeSessionId === session.id ? styles.sessionButtonActive : {}),
                    }}
                  >
                    <div style={styles.sessionButtonTitle}>{session.title}</div>
                    <div style={styles.sessionButtonMeta}>
                      {session.videoPath ? `${session.videoPath.split(/[\\/]/).pop()} • ${formatSessionDate(session.createdAt)}` : formatSessionDate(session.createdAt)}
                    </div>
                    <div style={styles.sessionButtonPreview}>{getSessionPreview(session)}</div>
                  </button>
                  <button onClick={() => requestDeleteSession(session.id)} style={styles.deleteSessionBtn} title="Delete session">
                    <Trash2 size={13} />
                  </button>
                </div>
              ))
            )}
          </div>
        )}
      </aside>

      <div style={styles.mainPane}>
        <header style={styles.header}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <MessageSquare size={24} color="#4ecdc4" />
            <div>
              <h2 style={{ margin: 0, fontSize: '18px', fontWeight: '600' }}>Local Video GenAI Workspace</h2>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <button onClick={clearCurrentSession} style={styles.secondaryBtn}>
              <RefreshCw size={15} /> Clear Session
            </button>
            <button onClick={browseLocalVideo} style={styles.primaryBtn}>
              <Video size={16} />
              {activeVideoPath ? `Selected: ${activeVideoPath.split(/[\\/]/).pop()}` : 'Browse Local .mp4'}
            </button>
          </div>
        </header>

        <main style={styles.chatArea}>
          {messages.length === 0 ? (
            <div style={styles.welcomeHero}>
              <Video size={48} color="#555" style={{ marginBottom: '15px' }} />
              <h3>No Active Video Context</h3>
              <p style={{ maxWidth: '420px', color: '#aaa', fontSize: '14px' }}>
                Open a new session, select a local MP4, and ask for transcription or analysis. Old runs stay available in the sidebar.
              </p>
            </div>
          ) : (
            messages.map((msg) => (
              <div key={msg.id} style={msg.sender === 'user' ? styles.userRow : styles.botRow}>
                <div style={msg.sender === 'user' ? styles.userBubble : styles.botBubble}>
                  <ReactMarkdown>{msg.text}</ReactMarkdown>
                  <span style={styles.timestamp}>{msg.timestamp}</span>
                </div>
              </div>
            ))
          )}

          {activeHitlPrompt && (
            <div style={styles.hitlCard}>
              <div style={{ display: 'flex', gap: '8px', marginBottom: '12px', alignItems: 'flex-start' }}>
                <AlertCircle color="#ff9800" size={20} style={{ flexShrink: 0, marginTop: '2px' }} />
                <p style={{ margin: 0, fontSize: '14px', fontWeight: '500' }}>{activeHitlPrompt.text}</p>
              </div>
              <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                {activeHitlPrompt.options.map((opt, index) => (
                  <button key={`${opt}-${index}`} onClick={() => transmitMessage(opt, opt)} style={styles.hitlOptionBtn}>
                    {opt}
                  </button>
                ))}
              </div>
            </div>
          )}
          <div ref={chatBottomRef} />
        </main>

        <footer style={styles.footer}>
          <div style={{ display: 'flex', width: '100%', gap: '10px' }}>
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && transmitMessage()}
              placeholder={activeVideoPath ? 'Ask the agent to transcribe, analyze graphs, or summarize...' : 'Select a local MP4 first to start analysis'}
              disabled={!activeVideoPath || isProcessing}
              style={styles.chatInput}
            />
            <button onClick={() => transmitMessage()} disabled={!activeVideoPath || isProcessing} style={styles.sendBtn}>
              <Send size={18} />
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}

const styles = {
  container: {
    display: 'flex',
    width: '100vw',
    height: '100vh',
    margin: 0,
    padding: 0,
    overflow: 'hidden',
    background: '#141414',
    color: '#e0e0e0',
    fontFamily: 'system-ui, sans-serif',
  },
  sidebar: {
    width: '260px',
    background: '#171717',
    borderRight: '1px solid #2d2d2d',
    display: 'flex',
    flexDirection: 'column',
    transition: 'width 0.2s ease',
    overflow: 'hidden',
  },
  sidebarCollapsed: {
    width: '72px',
  },
  sidebarHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '16px 14px',
    borderBottom: '1px solid #2d2d2d',
  },
  sidebarHeaderCollapsed: {
    flexDirection: 'column',
    justifyContent: 'space-between',
    alignItems: 'center',
    minHeight: '96px',
    padding: '12px 10px',
  },
  collapsedActionStack: {
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
    alignItems: 'center',
  },
  sidebarTitle: {
    margin: 0,
    fontSize: '15px',
    fontWeight: '600',
  },
  newSessionBtn: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: '32px',
    height: '32px',
    borderRadius: '50%',
    background: '#2a2a2a',
    color: '#fff',
    border: '1px solid #3d3d3d',
    cursor: 'pointer',
  },
  toggleSidebarBtn: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: '32px',
    height: '32px',
    borderRadius: '50%',
    background: '#1f1f1f',
    color: '#bbb',
    border: '1px solid #3d3d3d',
    cursor: 'pointer',
  },
  sessionList: {
    flex: 1,
    overflowY: 'auto',
    padding: '10px',
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
  },
  historyToolbar: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: '4px',
    padding: '2px 2px 8px',
  },
  historyToolbarLabel: {
    fontSize: '12px',
    color: '#888',
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
  },
  historyToolbarBtn: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: '28px',
    height: '28px',
    borderRadius: '6px',
    border: '1px solid #2d2d2d',
    background: '#1f1f1f',
    color: '#bbb',
    cursor: 'pointer',
  },
  sessionCard: {
    position: 'relative',
    display: 'flex',
    alignItems: 'stretch',
    gap: '6px',
  },
  emptyState: {
    color: '#777',
    fontSize: '13px',
    padding: '8px 6px',
  },
  sessionButton: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'flex-start',
    gap: '4px',
    width: '100%',
    minWidth: 0,
    padding: '10px 42px 10px 12px',
    borderRadius: '8px',
    background: '#1f1f1f',
    border: '1px solid #2d2d2d',
    color: '#e0e0e0',
    textAlign: 'left',
    cursor: 'pointer',
  },
  deleteSessionBtn: {
    position: 'absolute',
    top: '8px',
    right: '8px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: '28px',
    height: '28px',
    borderRadius: '6px',
    border: '1px solid #2d2d2d',
    background: '#1a1a1a',
    color: '#ff7b7b',
    cursor: 'pointer',
    zIndex: 1,
  },
  sessionButtonActive: {
    borderColor: '#4ecdc4',
    background: '#232323',
  },
  sessionButtonTitle: {
    fontSize: '13px',
    fontWeight: '600',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    width: '100%',
  },
  sessionButtonMeta: {
    color: '#888',
    fontSize: '11px',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    width: '100%',
  },
  sessionButtonPreview: {
    color: '#777',
    fontSize: '11px',
    lineHeight: 1.3,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    display: '-webkit-box',
    WebkitLineClamp: 2,
    WebkitBoxOrient: 'vertical',
    width: '100%',
    textAlign: 'left',
  },
  confirmOverlay: {
    position: 'fixed',
    inset: 0,
    background: 'rgba(0, 0, 0, 0.65)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 1000,
    padding: '16px',
  },
  confirmDialog: {
    width: '320px',
    maxWidth: '100%',
    background: '#1f1f1f',
    border: '1px solid #3a3a3a',
    borderRadius: '10px',
    padding: '16px',
    boxShadow: '0 12px 40px rgba(0, 0, 0, 0.35)',
  },
  confirmTitle: {
    margin: '0 0 8px',
    fontSize: '16px',
    color: '#fff',
  },
  confirmMessage: {
    margin: '0 0 16px',
    color: '#bbb',
    fontSize: '14px',
    lineHeight: 1.4,
  },
  confirmActions: {
    display: 'flex',
    justifyContent: 'flex-end',
    gap: '8px',
  },
  confirmCancelBtn: {
    padding: '8px 12px',
    borderRadius: '6px',
    border: '1px solid #3a3a3a',
    background: '#2a2a2a',
    color: '#fff',
    cursor: 'pointer',
  },
  confirmDeleteBtn: {
    padding: '8px 12px',
    borderRadius: '6px',
    border: '1px solid #8b2f2f',
    background: '#b33a3a',
    color: '#fff',
    cursor: 'pointer',
  },
  mainPane: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '12px 20px',
    background: '#1e1e1e',
    borderBottom: '1px solid #2d2d2d',
  },
  headerSubtitle: {
    marginTop: '2px',
    color: '#8d8d8d',
    fontSize: '12px',
  },
  primaryBtn: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    padding: '8px 14px',
    background: '#007acc',
    border: 'none',
    borderRadius: '5px',
    color: '#fff',
    cursor: 'pointer',
    fontWeight: '500',
    fontSize: '13px',
  },
  secondaryBtn: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    padding: '8px 12px',
    background: '#2d2d2d',
    border: '1px solid #3d3d3d',
    borderRadius: '5px',
    color: '#bbb',
    cursor: 'pointer',
    fontSize: '13px',
  },
  chatArea: {
    flex: 1,
    overflowY: 'auto',
    padding: '20px',
    display: 'flex',
    flexDirection: 'column',
    gap: '16px',
  },
  welcomeHero: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    height: '100%',
    textAlign: 'center',
    color: '#777',
  },
  userRow: { display: 'flex', justifyContent: 'flex-end' },
  botRow: { display: 'flex', justifyContent: 'flex-start' },
  userBubble: {
    background: '#007acc',
    color: '#fff',
    padding: '12px 16px',
    borderRadius: '12px 12px 2px 12px',
    maxWidth: '70%',
    boxShadow: '0 2px 4px rgba(0,0,0,0.2)',
  },
  botBubble: {
    background: '#222',
    color: '#e0e0e0',
    padding: '12px 16px',
    borderRadius: '12px 12px 12px 2px',
    maxWidth: '70%',
    border: '1px solid #2d2d2d',
    lineHeight: '1.5',
    boxShadow: '0 2px 4px rgba(0,0,0,0.2)',
  },
  timestamp: {
    display: 'block',
    fontSize: '10px',
    color: 'rgba(255,255,255,0.4)',
    marginTop: '6px',
    textAlign: 'right',
  },
  hitlCard: {
    background: '#2a1b0c',
    borderLeft: '4px solid #ff9800',
    padding: '16px',
    borderRadius: '6px',
    margin: '10px 0',
    boxShadow: '0 4px 6px rgba(0,0,0,0.3)',
  },
  hitlOptionBtn: {
    padding: '8px 14px',
    background: '#ff9800',
    border: 'none',
    borderRadius: '4px',
    color: '#000',
    fontWeight: '600',
    cursor: 'pointer',
    fontSize: '12px',
  },
  footer: {
    padding: '16px 20px',
    background: '#1e1e1e',
    borderTop: '1px solid #2d2d2d',
  },
  chatInput: {
    flex: 1,
    padding: '12px 16px',
    background: '#111',
    border: '1px solid #2d2d2d',
    borderRadius: '6px',
    color: '#fff',
    fontSize: '14px',
    outline: 'none',
  },
  sendBtn: {
    background: '#4ecdc4',
    color: '#111',
    border: 'none',
    borderRadius: '6px',
    width: '45px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    cursor: 'pointer',
  },
};