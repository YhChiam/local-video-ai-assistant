import React, { useState, useEffect, useRef } from 'react';
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { listen } from "@tauri-apps/api/event";
import { MessageSquare, Video, FileText, Send, RefreshCw, AlertCircle } from 'lucide-react';
import ReactMarkdown from 'react-markdown';

export default function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [videoPath, setVideoPath] = useState('');
  const [hitlPrompt, setHitlPrompt] = useState(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const chatBottomRef = useRef(null);

  // Load persistent chat log matrix from LocalStorage upon startup
  useEffect(() => {
    const savedChat = localStorage.getItem('offline_agent_history');
    if (savedChat) {
      setMessages(JSON.parse(savedChat));
    }
  }, []);

  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, hitlPrompt]);

  // Handle local desktop file browser dialog selection
  const browseLocalVideo = async () => {
    try {
      const selected = await open({
        multiple: false,
        filters: [{ name: 'Video Format', extensions: ['mp4'] }]
      });
      if (selected) {
        setVideoPath(selected);
      }
    } catch (err) {
      console.error("Native File Open Cancelled/Failed:", err);
    }
  };

  const persistHistory = (newHistory) => {
    setMessages(newHistory);
    localStorage.setItem('offline_agent_history', JSON.stringify(newHistory));
  };

  const clearChatLogs = () => {
    persistHistory([]);
    setHitlPrompt(null);
    setVideoPath('');
  };

  // Submit requests to the Tauri-Rust layer orchestrator
  const transmitMessage = async (explicitQuery = null, hitlSelection = null) => {
    const activeText = explicitQuery || input;
    if (!activeText.trim() && !hitlSelection) return;

    setIsProcessing(true);
    setHitlPrompt(null);

    const userBubble = {
      id: Date.now(),
      sender: 'user',
      text: hitlSelection ? `[Selected Option]: ${hitlSelection}` : activeText,
      timestamp: new Date().toLocaleTimeString()
    };

    const updatedHistory = [...messages, userBubble];
    persistHistory(updatedHistory);
    setInput('');

    // Allocate an empty temporary message object placeholder for the incoming stream chunk
    const responseId = Date.now() + 1;
    let baselineBotHistory = [...updatedHistory, { id: responseId, sender: 'bot', text: '⏳ Connecting to local agent sub-channels...' }];
    setMessages(baselineBotHistory);

    try {
      // Setup an active listener loop for the streaming data thrown back by Tauri Rust
      const unlisten = await listen('grpc-chunk-received', (event) => {
        const payload = event.payload; // Contains JSON parsed gRPC ChatResponse model

        if (payload.type === "CLARIFICATION_REQUIRED") {
          setHitlPrompt({
            text: payload.content,
            options: payload.clarification_options
          });
          // Strip out the placeholder processing text
          baselineBotHistory = baselineBotHistory.filter(m => m.id !== responseId);
          persistHistory(baselineBotHistory);
        } else if (payload.type === "REPORT_GENERATED") {
          baselineBotHistory = baselineBotHistory.map(m => 
            m.id === responseId 
              ? { ...m, text: `${payload.content}\n\n📁 **Export Location:** [Open Document Path](${payload.file_url})` }
              : m
          );
          persistHistory(baselineBotHistory);
        } else {
          // Continuous Markdown Appends (TEXT_CHUNK)
          baselineBotHistory = baselineBotHistory.map(m => 
            m.id === responseId 
              ? { ...m, text: m.text === '⏳ Connecting to local agent sub-channels...' ? payload.content : m.text + payload.content }
              : m
          );
          persistHistory(baselineBotHistory);
        }
      });

      // Call the rust broker handle execution command block
      await invoke('route_agent_query', {
        userQuery: activeText,
        videoPath: videoPath,
        isClarification: hitlSelection !== null,
        selectedOption: hitlSelection || ""
      });

      unlisten(); // Tear down event capture channel hooks cleanly after stream completion
    } catch (err) {
      baselineBotHistory = baselineBotHistory.map(m => 
        m.id === responseId ? { ...m, text: `❌ **Local Communication Error:** ${err.toString()}` } : m
      );
      persistHistory(baselineBotHistory);
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <div className="app-container" style={styles.container}>
      {/* Upper Navigation / Control Deck */}
      <header style={styles.header}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <MessageSquare size={24} color="#4ecdc4" />
          <h2 style={{ margin: 0, fontSize: '18px', fontWeight: '600' }}>Local Video GenAI Solution Workspace</h2>
        </div>
        
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <button onClick={clearChatLogs} style={styles.secondaryBtn}>
            <RefreshCw size={15} /> Clear History
          </button>
          
          <button onClick={browseLocalVideo} style={styles.primaryBtn}>
            <Video size={16} /> 
            {videoPath ? `Selected: ${videoPath.split(/[\\/]/).pop()}` : 'Browse Local .mp4'}
          </button>
        </div>
      </header>

      {/* Primary Conversational Workspace */}
      <main style={styles.chatArea}>
        {messages.length === 0 ? (
          <div style={styles.welcomeHero}>
            <Video size={48} color="#555" style={{ marginBottom: '15px' }} />
            <h3>No Active Video Context Isolated</h3>
            <p style={{ maxWidth: '400px', color: '#aaa', fontSize: '14px' }}>
              Select a 1-minute video frame file using the control deck button above to initialize offline transcription or chart evaluation.
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

        {/* Human-in-the-Loop Clarification Interceptor Interface */}
        {hitlPrompt && (
          <div style={styles.hitlCard}>
            <div style={{ display: 'flex', gap: '8px', marginBottom: '12px', alignItems: 'flex-start' }}>
              <AlertCircle color="#ff9800" size={20} style={{ flexShrink: 0, marginTop: '2px' }} />
              <p style={{ margin: 0, fontSize: '14px', fontWeight: '500' }}>{hitlPrompt.text}</p>
            </div>
            <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
              {hitlPrompt.options.map((opt, i) => (
                <button key={i} onClick={() => transmitMessage(opt, opt)} style={styles.hitlOptionBtn}>
                  {opt}
                </button>
              ))}
            </div>
          </div>
        )}
        <div ref={chatBottomRef} />
      </main>

      {/* Lower Interactive Terminal Bar */}
      <footer style={styles.footer}>
        <div style={{ display: 'flex', width: '100%', gap: '10px' }}>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && transmitMessage()}
            placeholder={videoPath ? "Ask the Agent Cluster to: Transcribe, analyze graphs, or print a PDF summary..." : "🔒 Please establish a video context above to start analysis"}
            disabled={!videoPath || isProcessing}
            style={styles.chatInput}
          />
          <button onClick={() => transmitMessage()} disabled={!videoPath || isProcessing} style={styles.sendBtn}>
            <Send size={18} />
          </button>
        </div>
      </footer>
    </div>
  );
}

const styles = {
  container: { display: 'flex', flexDirection: 'column', height: '100vh', background: '#141414', color: '#e0e0e0', fontFamily: 'system-ui, sans-serif' },
  header: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 20px', background: '#1e1e1e', borderBottom: '1px solid #2d2d2d' },
  primaryBtn: { display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 14px', background: '#007acc', border: 'none', borderRadius: '5px', color: '#fff', cursor: 'pointer', fontWeight: '500', fontSize: '13px' },
  secondaryBtn: { display: 'flex', alignItems: 'center', gap: '6px', padding: '8px 12px', background: '#2d2d2d', border: '1px solid #3d3d3d', borderRadius: '5px', color: '#bbb', cursor: 'pointer', fontSize: '13px' },
  chatArea: { flex: 1, overflowY: 'auto', padding: '20px', display: 'flex', flexDirection: 'column', gap: '16px' },
  welcomeHero: { display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', textAlign: 'center', color: '#777' },
  userRow: { display: 'flex', justifyContent: 'flex-end' },
  botRow: { display: 'flex', justifyContent: 'flex-start' },
  userBubble: { background: '#007acc', color: '#fff', padding: '12px 16px', borderRadius: '12px 12px 2px 12px', maxWidth: '70%', boxShadow: '0 2px 4px rgba(0,0,0,0.2)' },
  botBubble: { background: '#222', color: '#e0e0e0', padding: '12px 16px', borderRadius: '12px 12px 12px 2px', maxWidth: '70%', border: '1px solid #2d2d2d', lineHeight: '1.5', boxShadow: '0 2px 4px rgba(0,0,0,0.2)' },
  timestamp: { display: 'block', fontSize: '10px', color: 'rgba(255,255,255,0.4)', marginTop: '6px', textAlign: 'right' },
  hitlCard: { background: '#2a1b0c', borderLeft: '4px solid #ff9800', padding: '16px', borderRadius: '6px', margin: '10px 0', boxShadow: '0 4px 6px rgba(0,0,0,0.3)' },
  hitlOptionBtn: { padding: '8px 14px', background: '#ff9800', border: 'none', borderRadius: '4px', color: '#000', fontWeight: '600', cursor: 'pointer', fontSize: '12px', transition: 'background 0.2s' },
  footer: { padding: '16px 20px', background: '#1e1e1e', borderTop: '1px solid #2d2d2d' },
  chatInput: { flex: 1, padding: '12px 16px', background: '#111', border: '1px solid #2d2d2d', borderRadius: '6px', color: '#fff', fontSize: '14px', outline: 'none' },
  sendBtn: { background: '#4ecdc4', color: '#111', border: 'none', borderRadius: '6px', width: '45px', display: 'flex', alignItems: 'center', justifyValue: 'center', justifyContent: 'center', cursor: 'pointer' }
};