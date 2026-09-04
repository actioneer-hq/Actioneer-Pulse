import {
  useCallback, useEffect, useMemo, useRef, useState,
  type KeyboardEvent, type ReactNode,
} from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  createConversation,
  deleteConversation,
  getConversation,
  listCalls,
  listConversations,
  streamChat,
  type ChatMsg,
  type ChatStep,
  type Conversation,
} from "../api";
import { useAuth } from "../auth";

const MENTION = /@([\w-]+)/g;  // @<callId> token

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
        <Composer value={input} onChange={setInput} onSend={send} sending={sending} />
      </div>
    </div>
  );
}

// Chat composer with @call-id mentions: a transparent textarea over a mirror div that renders
// the @<callId> token highlighted. Typing @ opens a call-id autocomplete. UI only for now —
// the mention doesn't yet load that call's context (harness comes later).
function Composer(
  { value, onChange, onSend, sending }:
  { value: string; onChange: (v: string) => void; onSend: () => void; sending: boolean },
) {
  const taRef = useRef<HTMLTextAreaElement>(null);
  const hlRef = useRef<HTMLDivElement>(null);
  const [callIds, setCallIds] = useState<string[]>([]);
  const [menu, setMenu] = useState<{ query: string; start: number; sel: number } | null>(null);

  useEffect(() => { listCalls(200).then((cs) => setCallIds(cs.map((c) => c.id))).catch(() => {}); }, []);

  const suggestions = useMemo(() => {
    if (menu === null) return [];
    const q = menu.query.toLowerCase();
    return callIds.filter((id) => id.toLowerCase().includes(q)).slice(0, 6);
  }, [menu, callIds]);

  function syncScroll() {
    if (hlRef.current && taRef.current) hlRef.current.scrollTop = taRef.current.scrollTop;
  }

  function detect(v: string, caret: number) {
    // an @token immediately before the caret opens the menu
    const m = /@([\w-]*)$/.exec(v.slice(0, caret));
    setMenu(m ? { query: m[1], start: caret - m[0].length, sel: 0 } : null);
  }

  function change(v: string) {
    onChange(v);
    const caret = taRef.current?.selectionStart ?? v.length;
    detect(v, caret);
  }

  function pick(id: string) {
    if (menu === null) return;
    const before = value.slice(0, menu.start);
    const after = value.slice(menu.start + 1 + menu.query.length);
    const next = `${before}@${id} ${after}`;
    onChange(next);
    setMenu(null);
    requestAnimationFrame(() => {
      const pos = before.length + id.length + 2;
      taRef.current?.focus();
      taRef.current?.setSelectionRange(pos, pos);
    });
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (menu && suggestions.length) {
      if (e.key === "ArrowDown") { e.preventDefault(); setMenu({ ...menu, sel: (menu.sel + 1) % suggestions.length }); return; }
      if (e.key === "ArrowUp") { e.preventDefault(); setMenu({ ...menu, sel: (menu.sel - 1 + suggestions.length) % suggestions.length }); return; }
      if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); pick(suggestions[menu.sel]); return; }
      if (e.key === "Escape") { setMenu(null); return; }
    }
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onSend(); }
  }

  return (
    <div className="composer">
      {menu && suggestions.length > 0 && (
        <div className="mention-menu">
          {suggestions.map((id, i) => (
            <button key={id} className={`mention-opt ${i === menu.sel ? "on" : ""}`}
              onMouseDown={(e) => { e.preventDefault(); pick(id); }}>
              <span className="mention-at">@</span><span className="mono">{id}</span>
            </button>
          ))}
        </div>
      )}
      <div className="composer-box">
        <div className="composer-hl" ref={hlRef} aria-hidden="true">{highlight(value)}</div>
        <textarea ref={taRef} value={value} rows={1}
          onChange={(e) => change(e.target.value)} onKeyDown={onKey} onScroll={syncScroll}
          placeholder="Ask about your calls…  (type @ to reference a call)" />
        <button className="composer-send" disabled={!value.trim() || sending} onClick={onSend}
          aria-label="Send">↑</button>
      </div>
    </div>
  );
}

// Render text with @<callId> tokens wrapped in a highlight mark (for the mirror layer).
function highlight(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(MENTION)) {
    if (m.index > last) out.push(text.slice(last, m.index));
    out.push(<mark className="mention" key={m.index}>{m[0]}</mark>);
    last = m.index + m[0].length;
  }
  out.push(text.slice(last));
  out.push("\n");  // trailing newline so the mirror matches the textarea's height growth
  return out;
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
