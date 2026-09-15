import { Button } from "@actioneer/ads";
import {
  useCallback, useEffect, useMemo, useRef, useState,
  type KeyboardEvent, type ReactNode,
} from "react";
import {
  createConversation,
  deleteConversation,
  getConversation,
  listCalls,
  listConversations,
  streamChat,
  type ChatStep,
  type Conversation,
} from "../api";
import { useActiveAgent } from "../ActiveAgentProvider";
import { useAuth } from "../auth";
import { Bubble, type LiveMsg } from "../components/chat/Bubble";
import { AudioToggle } from "../components/chat/AudioToggle";

// Per-conversation audio-native state, kept alongside threads so it reloads on switch.
type AudioState = { enabled: boolean; available: boolean };

const MENTION = /@([\w-]+)/g;  // @<callId> token

// One thread's live state, kept per-conversation so multiple chats stream at once.
type Thread = { messages: LiveMsg[]; streaming: boolean };

export default function Chat() {
  const { activeOrg } = useAuth();
  const [convos, setConvos] = useState<Conversation[]>([]);
  const [active, setActive] = useState<string | null>(null);
  // A registry of threads by conversation id — a stream mutates its own thread, so switching the
  // shown conversation never cancels or clobbers an in-flight stream on another.
  const [threads, setThreads] = useState<Record<string, Thread>>({});
  const [audio, setAudio] = useState<Record<string, AudioState>>({});
  const [input, setInput] = useState("");
  const threadRef = useRef<HTMLDivElement>(null);

  const messages = (active && threads[active]?.messages) || [];
  const activeStreaming = !!(active && threads[active]?.streaming);

  const loadConvos = useCallback(() => {
    listConversations().then(setConvos).catch(() => setConvos([]));
  }, []);
  useEffect(() => { loadConvos(); setActive(null); setThreads({}); setAudio({}); }, [loadConvos, activeOrg]);

  // Load a conversation's messages on first view — but never refetch a thread that already has local
  // state (loaded or mid-stream), or we'd wipe an in-flight stream.
  useEffect(() => {
    if (!active || threads[active]) return;
    getConversation(active)
      .then((c) => {
        setThreads((t) => (t[active] ? t : { ...t, [active]: { messages: c.messages, streaming: false } }));
        setAudio((a) => ({ ...a, [active]: { enabled: c.audio_native_enabled, available: c.audio_native_available } }));
      })
      .catch(() => setThreads((t) => ({ ...t, [active]: { messages: [], streaming: false } })));
  }, [active, threads]);

  // autoscroll to bottom as the shown thread streams in
  useEffect(() => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight });
  }, [messages]);

  // Update the last message of a specific thread (keyed by cid, not the shown one).
  const updLast = (cid: string, fn: (a: LiveMsg) => LiveMsg) =>
    setThreads((t) => {
      const th = t[cid];
      if (!th) return t;
      const n = th.messages.length;
      return { ...t, [cid]: { ...th, messages: th.messages.map((m, i) => (i === n - 1 ? fn(m) : m)) } };
    });

  async function newChat() {
    const c = await createConversation();
    setConvos((cs) => [{ id: c.id, title: c.title }, ...cs]);
    setThreads((t) => ({ ...t, [c.id]: { messages: [], streaming: false } }));
    setAudio((a) => ({ ...a, [c.id]: { enabled: c.audio_native_enabled, available: c.audio_native_available } }));
    setActive(c.id);
  }

  async function remove(id: string) {
    if (!confirm("Delete this conversation?")) return;
    await deleteConversation(id);
    setThreads((t) => { const { [id]: _drop, ...rest } = t; return rest; });
    if (active === id) setActive(null);
    loadConvos();
  }

  async function send() {
    const text = input.trim();
    // Only block a second send to the SAME thread; other threads can stream concurrently.
    if (!text || activeStreaming) return;
    let cid = active;
    if (!cid) {
      const c = await createConversation(); cid = c.id;
      setAudio((a) => ({ ...a, [c.id]: { enabled: c.audio_native_enabled, available: c.audio_native_available } }));
      setActive(cid); loadConvos();
    }
    const id = cid!;
    setInput("");
    setThreads((t) => ({ ...t, [id]: {
      streaming: true,
      messages: [...(t[id]?.messages ?? []),
        { role: "user", content: text, steps: [] },
        { role: "assistant", content: "", steps: [], streaming: true }],
    } }));

    try {
      await streamChat(id, text, (e) => {
        if (e.type === "token") updLast(id, (a) => ({ ...a, content: a.content + e.text }));
        else if (e.type === "tool_call")
          updLast(id, (a) => ({ ...a, steps: [...a.steps, { name: e.name, args: e.args, summary: "…" } as ChatStep] }));
        else if (e.type === "tool_result")
          updLast(id, (a) => ({ ...a, steps: a.steps.map((s, i) =>
            i === a.steps.length - 1 ? { ...s, summary: e.summary } : s) }));
        else if (e.type === "error")
          updLast(id, (a) => ({ ...a, content: a.content || `⚠️ ${e.error}`, streaming: false }));
      });
    } catch { updLast(id, (a) => ({ ...a, content: a.content || "⚠️ stream failed" })); }
    updLast(id, (a) => ({ ...a, streaming: false }));
    setThreads((t) => (t[id] ? { ...t, [id]: { ...t[id], streaming: false } } : t));
    loadConvos();  // refresh titles/order
  }


  return (
    <div className="chat">
      <aside className="chat-side">
        <Button className="chat-new" fullWidth onClick={newChat}>+ New chat</Button>
        <div className="chat-list">
          {convos.map((c) => (
            <div key={c.id} className={`chat-item ${c.id === active ? "on" : ""}`}
              onClick={() => setActive(c.id)}>
              {threads[c.id]?.streaming && <span className="chat-streaming" title="Responding…" />}
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
        <div className="composer-tools">
          <AudioToggle
            cid={active}
            enabled={!!(active && audio[active]?.enabled)}
            available={!!(active && audio[active]?.available)}
            onChange={(v) => active && setAudio((a) => ({
              ...a, [active]: { enabled: v, available: a[active]?.available ?? false },
            }))}
          />
        </div>
        <Composer value={input} onChange={setInput} onSend={send} sending={activeStreaming} />
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
  const { activeAgent } = useActiveAgent();
  const taRef = useRef<HTMLTextAreaElement>(null);
  const hlRef = useRef<HTMLDivElement>(null);
  const [callIds, setCallIds] = useState<string[]>([]);
  const [menu, setMenu] = useState<{ query: string; start: number; sel: number } | null>(null);

  useEffect(() => {
    listCalls(200, activeAgent || undefined).then((cs) => setCallIds(cs.map((c) => c.id))).catch(() => {});
  }, [activeAgent]);

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

