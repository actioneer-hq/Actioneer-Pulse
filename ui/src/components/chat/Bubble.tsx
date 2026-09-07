import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMsg, ChatStep } from "../../api";

// A message that's mid-stream: content grows, steps accumulate, `streaming` until done.
export type LiveMsg = ChatMsg & { streaming?: boolean };

// Renders one chat message — user bubble, or the assistant's activity (tool steps + SQL) and
// streamed markdown. Shared by the global Chat page and the per-call CallChat panel.
export function Bubble({ msg }: { msg: LiveMsg }) {
  if (msg.role === "user") {
    return <div className="msg-row user"><div className="msg-user">{msg.content}</div></div>;
  }
  return (
    <div className="msg-row assistant">
      {msg.steps.length > 0 && (
        <div className="activity">
          {msg.steps.map((s, i) => (
            <div className="step" key={i}>
              <div><span className="step-dot" /> {stepLabel(s)}</div>
              {s.name === "execute_sql" && (s.args as { query?: string })?.query && (
                <pre className="step-sql">{(s.args as { query?: string }).query}</pre>
              )}
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

export function stepLabel(s: ChatStep): string {
  const verb = s.name === "execute_sql" ? "Ran SQL" : s.name;
  return s.summary === "…" ? `${verb === "Ran SQL" ? "Running SQL" : verb}…` : `${verb} · ${s.summary}`;
}
