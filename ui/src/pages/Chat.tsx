import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  createConversation,
  deleteConversation,
  getConversation,
  listConversations,
  streamChat,
  type ChatMsg,
  type ChatStep,
  type Conversation,
} from "../api";
import { useAuth } from "../auth";

// A message that's mid-stream: content grows, steps accumulate, `streaming` until done.
type LiveMsg = ChatMsg & { streaming?: boolean };

export default function Chat() {
  const { activeOrg } = useAuth();
  const [convos, setConvos] = useState<Conversation[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [messages, setMessages] = useState<LiveMsg[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const threadRef = useRef<HTMLDivElement>(null);

  const loadConvos = useCallback(() => {
    listConversations().then(setConvos).catch(() => setConvos([]));
  }, []);
  useEffect(() => { loadConvos(); setActive(null); setMessages([]); }, [loadConvos, activeOrg]);

  // load a conversation's messages when selected
  useEffect(() => {
    if (!active) { setMessages([]); return; }
    getConversation(active).then((c) => setMessages(c.messages)).catch(() => setMessages([]));
  }, [active]);

  // autoscroll to bottom as content streams in
  useEffect(() => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight });
  }, [messages]);

  async function newChat() {
    const c = await createConversation();
    setConvos((cs) => [{ id: c.id, title: c.title }, ...cs]);
    setActive(c.id);
    setMessages([]);
  }

  async function remove(id: string) {
    if (!confirm("Delete this conversation?")) return;
    await deleteConversation(id);
    if (active === id) { setActive(null); setMessages([]); }
    loadConvos();
  }

  async function send() {
    const text = input.trim();
    if (!text || sending) return;
    let cid = active;
    if (!cid) { const c = await createConversation(); cid = c.id; setActive(cid); loadConvos(); }
    setInput("");
    setSending(true);
    setMessages((m) => [...m,
      { role: "user", content: text, steps: [] },
      { role: "assistant", content: "", steps: [], streaming: true }]);

    const upd = (fn: (a: LiveMsg) => LiveMsg) =>
      setMessages((m) => m.map((msg, i) => (i === m.length - 1 ? fn(msg) : msg)));

    try {
      await streamChat(cid!, text, (e) => {
        if (e.type === "token") upd((a) => ({ ...a, content: a.content + e.text }));
        else if (e.type === "tool_call")
          upd((a) => ({ ...a, steps: [...a.steps, { name: e.name, summary: "…" } as ChatStep] }));
        else if (e.type === "tool_result")
          upd((a) => ({ ...a, steps: a.steps.map((s, i) =>
            i === a.steps.length - 1 ? { ...s, summary: e.summary } : s) }));
        else if (e.type === "error")
          upd((a) => ({ ...a, content: a.content || `⚠️ ${e.error}`, streaming: false }));
      });
    } catch { upd((a) => ({ ...a, content: a.content || "⚠️ stream failed" })); }
    upd((a) => ({ ...a, streaming: false }));
    setSending(false);
    loadConvos();  // refresh titles/order
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  }

  return (
    <div className="chat">
      <aside className="chat-side">
        <button className="btn-primary chat-new" onClick={newChat}>+ New chat</button>
        <div className="chat-list">
          {convos.map((c) => (
            <div key={c.id} className={`chat-item ${c.id === active ? "on" : ""}`}
              onClick={() => setActive(c.id)}>
              <span className="chat-title">{c.title}</span>
              <button className="chat-del" onClick={(e) => { e.stopPropagation(); remove(c.id); }}
                title="Delete">×</button>
            </div>
          ))}
          {convos.length === 0 && <div className="dimtxt pad">No conversations yet.</div>}
        </div>
      </aside>

      <div className="chat-main">
        <div className="chat-thread" ref={threadRef}>
          {messages.length === 0 && (
            <div className="chat-welcome"><h1>How can I help?</h1>
              <p className="sub">Ask about your calls — volume, failures, sentiment, a specific call…</p>
            </div>
          )}
          {messages.map((m, i) => <Bubble key={i} msg={m} />)}
        </div>
        <div className="composer">
          <textarea value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={onKey}
            rows={1} placeholder="Ask about your calls…" />
          <button className="composer-send" disabled={!input.trim() || sending} onClick={send}
            aria-label="Send">↑</button>
        </div>
      </div>
    </div>
  );
}

function Bubble({ msg }: { msg: LiveMsg }) {
  if (msg.role === "user") {
    return <div className="msg-row user"><div className="msg-user">{msg.content}</div></div>;
  }
  return (
    <div className="msg-row assistant">
      {msg.steps.length > 0 && (
        <div className="activity">
          {msg.steps.map((s, i) => (
            <div className="step" key={i}>
              <span className="step-dot" /> {stepLabel(s)}
            </div>
          ))}
        </div>
      )}
      <div className="msg-assistant prose">
        {msg.content
          ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
          : (msg.streaming && <span className="cursor">▍</span>)}
        {msg.content && msg.streaming && <span className="cursor">▍</span>}
      </div>
    </div>
  );
}

function stepLabel(s: ChatStep): string {
  const verb = s.name === "search_calls" ? "Searching calls"
    : s.name === "get_call" ? "Reading call" : s.name;
  return s.summary === "…" ? `${verb}…` : `${verb} · ${s.summary}`;
}
