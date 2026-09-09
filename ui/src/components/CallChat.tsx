import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { getCallChat, streamCallChat, type ChatStep } from "../api";
import { Bubble, type LiveMsg } from "./chat/Bubble";
import { AudioToggle } from "./chat/AudioToggle";

// A chat scoped to one call. History persists per call; the agent answers from the call's
// dumped transcript/metrics/analysis and can run execute_sql over this call's spans.
export default function CallChat({ callId }: { callId: string }) {
  const [msgs, setMsgs] = useState<LiveMsg[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  // Conversation id + audio-native state for this call's chat (from GET /v1/calls/{id}/chat).
  const [cid, setCid] = useState<string | null>(null);
  const [audio, setAudio] = useState<{ enabled: boolean; available: boolean }>(
    { enabled: false, available: false });
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getCallChat(callId)
      .then((d) => {
        setMsgs(d.messages as LiveMsg[]);
        setCid(d.id);
        setAudio({ enabled: d.audio_native_enabled, available: d.audio_native_available });
      })
      .catch(() => { setMsgs([]); setCid(null); });
  }, [callId]);

  useEffect(() => { endRef.current?.scrollIntoView({ block: "end" }); }, [msgs]);

  async function send() {
    const text = input.trim();
    if (!text || sending) return;
    setInput("");
    setSending(true);
    setMsgs((m) => [...m,
      { role: "user", content: text, steps: [] },
      { role: "assistant", content: "", steps: [], streaming: true }]);
    const upd = (fn: (a: LiveMsg) => LiveMsg) =>
      setMsgs((m) => m.map((msg, i) => (i === m.length - 1 ? fn(msg) : msg)));
    try {
      await streamCallChat(callId, text, (e) => {
        if (e.type === "token") upd((a) => ({ ...a, content: a.content + e.text }));
        else if (e.type === "tool_call")
          upd((a) => ({ ...a, steps: [...a.steps, { name: e.name, args: e.args, summary: "…" } as ChatStep] }));
        else if (e.type === "tool_result")
          upd((a) => ({ ...a, steps: a.steps.map((s, i) =>
            i === a.steps.length - 1 ? { ...s, summary: e.summary } : s) }));
        else if (e.type === "error")
          upd((a) => ({ ...a, content: a.content || `⚠️ ${e.error}`, streaming: false }));
      });
    } catch { upd((a) => ({ ...a, content: a.content || "⚠️ stream failed" })); }
    upd((a) => ({ ...a, streaming: false }));
    setSending(false);
  }

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); }
  };

  return (
    <div className="call-chat">
      <div className="call-chat-thread">
        {msgs.length === 0 && (
          <p className="dimtxt">Ask about this call — the transcript, metrics, and analysis are
            already in context; the agent can dig into the spans if needed.</p>
        )}
        {msgs.map((m, i) => <Bubble key={i} msg={m} />)}
        <div ref={endRef} />
      </div>
      <div className="composer-tools">
        <AudioToggle cid={cid} enabled={audio.enabled} available={audio.available}
          onChange={(v) => setAudio((a) => ({ ...a, enabled: v }))} />
      </div>
      <div className="call-chat-composer">
        <textarea value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={onKey}
          rows={2} placeholder="Ask about this call…" disabled={sending} />
        <button className="btn-primary" onClick={() => void send()} disabled={!input.trim() || sending}>
          Send</button>
      </div>
    </div>
  );
}
